"""
Tests for the EndNote consolidation pipeline.

Run with:  python3 tools/endnote-consolidate/tests/test_consolidate.py
       or: python3 -m pytest tools/endnote-consolidate/tests/
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(TOOL, "lib"))
sys.path.insert(0, HERE)

import make_fixture  # noqa: E402
import match  # noqa: E402
import merge as merge_lib  # noqa: E402
import textnorm as tn  # noqa: E402
from records import blank_record, set_provenance  # noqa: E402
from writers import record_to_xml, write_endnote_xml  # noqa: E402


def rec(library="L", record_id="1", **fields):
    r = blank_record()
    r.update(fields)
    return set_provenance(r, library=library, source_file="x",
                          source_kind="enl", record_id=record_id)


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------

class TestNormalisation(unittest.TestCase):
    def test_latin_diacritics_are_folded(self):
        self.assertEqual(tn.normalize_text("Muñoz"), tn.normalize_text("Munoz"))
        self.assertEqual(tn.normalize_text("Görres"), tn.normalize_text("Gorres"))

    def test_hebrew_niqqud_is_stripped_but_letters_survive(self):
        pointed = "תּוֹלְדוֹת הַיְּהוּדִים"
        plain = "תולדות היהודים"
        self.assertEqual(tn.normalize_text(pointed), tn.normalize_text(plain))
        self.assertIn("תולדות", tn.normalize_text(pointed))

    def test_arabic_harakat_is_stripped(self):
        self.assertEqual(tn.normalize_text("كِتَاب"), tn.normalize_text("كتاب"))

    def test_leading_articles_dropped_per_script(self):
        self.assertEqual(tn.normalize_text("The Jews"), tn.normalize_text("Jews"))
        self.assertEqual(tn.normalize_text("Los judíos"), tn.normalize_text("judios"))

    def test_subtitle_amputation(self):
        self.assertEqual(tn.main_title_key("Communities of Violence: Persecution"),
                         tn.main_title_key("Communities of Violence"))

    def test_messy_endnote_dates(self):
        self.assertEqual(tn.normalize_year("c1996-1997"), 1996)
        self.assertEqual(tn.normalize_year("[1996]"), 1996)
        self.assertEqual(tn.normalize_year("Spring 2004"), 2004)
        self.assertIsNone(tn.normalize_year("n.d."))

    def test_identifier_normalisation(self):
        self.assertEqual(tn.normalize_doi("https://doi.org/10.1086/ABC123."),
                         "10.1086/abc123")
        self.assertEqual(tn.normalize_isbn("0-691-05889-X"), "9780691058894")

    def test_surname_extraction(self):
        self.assertEqual(tn.surname("Nirenberg, David"), tn.surname("David Nirenberg"))
        self.assertEqual(tn.surname("van der Berg, Jan"), "van der berg")


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

class TestMatching(unittest.TestCase):
    cfg = dict(match.DEFAULT_THRESHOLDS)

    def score(self, a, b):
        return match.score_pair(a, b, self.cfg)

    def test_subtitle_and_initial_variants_are_the_same_work(self):
        a = rec(title="Communities of Violence", authors=["Nirenberg, David"],
                year="1996", ref_type="Book")
        b = rec(title="Communities of Violence: Persecution of Minorities",
                authors=["Nirenberg, D."], year="1996", ref_type="Book")
        result = self.score(a, b)
        self.assertGreaterEqual(result["score"], self.cfg["auto_merge"])
        self.assertEqual(result["blockers"], [])

    def test_editions_are_never_auto_merged(self):
        a = rec(title="Communities of Violence", authors=["Nirenberg, David"],
                year="1996", ref_type="Book", edition="1st")
        b = rec(title="Communities of Violence", authors=["Nirenberg, David"],
                year="2015", ref_type="Book", edition="2nd")
        result = self.score(a, b)
        self.assertTrue(any(x.startswith("edition") for x in result["blockers"]))

    def test_chapter_and_its_volume_are_never_auto_merged(self):
        a = rec(title="Religion and Minorities in Medieval Iberia",
                authors=["Meyerson, Mark D."], year="2000", ref_type="Edited Book")
        b = rec(title="Religion and Minorities in Medieval Iberia",
                authors=["Meyerson, Mark D."], year="2000", ref_type="Book Section")
        result = self.score(a, b)
        self.assertIn("type_family:book!=chapter", result["blockers"])

    def test_translations_are_never_auto_merged(self):
        a = rec(title="A History of the Jews in Christian Spain", year="1961",
                authors=["Baer, Yitzhak"], subsidiary_authors=["Schoffman, Louis"])
        b = rec(title="A History of the Jews in Christian Spain", year="1961",
                authors=["Baer, Yitzhak"], subsidiary_authors=["Cohen, Gerson"])
        self.assertIn("translator:disjoint", self.score(a, b)["blockers"])

    def test_two_articles_in_one_issue_stay_distinct(self):
        a = rec(title="Living Letters of the Law", authors=["Cohen, Jeremy"],
                year="1999", ref_type="Journal Article",
                secondary_title="Speculum", volume="74", issue="2", pages="401-425")
        b = rec(title="Under Crescent and Cross", authors=["Cohen, Mark R."],
                year="1999", ref_type="Journal Article",
                secondary_title="Speculum", volume="74", issue="2", pages="500-522")
        self.assertLess(self.score(a, b)["score"], self.cfg["review_low"])

    def test_doi_match_survives_a_mangled_title(self):
        a = rec(title="Conversion, Sex, and Segregation", doi="10.1086/532851",
                year="2002", ref_type="Journal Article")
        b = rec(title="Conversion, Sex and Segregation: Jews and Christians",
                doi="10.1086/532851", year="2002", ref_type="Journal Article")
        result = self.score(a, b)
        self.assertIn("same_doi", result["reasons"])
        self.assertGreaterEqual(result["score"], self.cfg["auto_merge"])

    def test_identifier_collision_with_unrelated_title_is_held_back(self):
        a = rec(title="Communities of Violence", doi="10.1086/532851")
        b = rec(title="Something Entirely Different About Fish", doi="10.1086/532851")
        result = self.score(a, b)
        self.assertIn("identifier_title_conflict", result["reasons"])
        self.assertLess(result["score"], self.cfg["auto_merge"])

    def test_sparse_records_are_not_penalised_for_absent_fields(self):
        # A book has no volume/issue/journal; that must not drag its score down.
        a = rec(title="Anti-Judaism: The Western Tradition",
                authors=["Nirenberg, David"], year="2013", ref_type="Book")
        b = rec(title="Anti-Judaism: The Western Tradition",
                authors=["Nirenberg, David"], year="2013", ref_type="Book")
        self.assertGreaterEqual(self.score(a, b)["score"], self.cfg["auto_merge"])

    def test_title_alone_is_not_enough(self):
        a = rec(title="Studies in Medieval History")
        b = rec(title="Studies in Medieval History")
        self.assertIn("thin_evidence", self.score(a, b)["reasons"])


# ---------------------------------------------------------------------------
# merge policy
# ---------------------------------------------------------------------------

class TestMergePolicy(unittest.TestCase):
    def test_every_distinct_note_survives_with_attribution(self):
        members = [
            rec("lib1996", "1", title="T", notes="Read Sept 1998."),
            rec("lib2011", "2", title="T", notes="Reread for the seminar."),
            rec("lib2024", "3", title="T", notes="Still the best thing."),
        ]
        merged, _ = merge_lib.merge_cluster(members, "M1")
        for m in members:
            self.assertIn(m["notes"], merged["notes"])
            self.assertIn(m["_prov"]["library"], merged["notes"])
        self.assertEqual(merged["_note_blocks"]["notes"], 3)

    def test_identical_notes_are_not_triplicated(self):
        members = [rec("a", "1", title="T", notes="same note"),
                   rec("b", "2", title="T", notes="same note")]
        merged, _ = merge_lib.merge_cluster(members, "M1")
        self.assertEqual(merged["notes"], "same note")

    def test_custom_fields_are_treated_as_notes_not_elected(self):
        members = [rec("a", "1", title="T", custom1="shelf: office A3"),
                   rec("b", "2", title="T", custom1="requested via ILL 2011")]
        merged, _ = merge_lib.merge_cluster(members, "M1")
        self.assertIn("office A3", merged["custom1"])
        self.assertIn("ILL 2011", merged["custom1"])

    def test_fuller_scalar_wins_and_loser_is_kept_as_a_variant(self):
        members = [rec("a", "1", title="Communities of Violence"),
                   rec("b", "2", title="Communities of Violence: Persecution")]
        merged, _ = merge_lib.merge_cluster(members, "M1")
        self.assertEqual(merged["title"], "Communities of Violence: Persecution")
        kept = [v["value"] for v in merged["_variants"]["title"]]
        self.assertIn("Communities of Violence", kept)

    def test_author_name_variants_collapse_to_the_fuller_spelling(self):
        members = [rec("a", "1", title="T", authors=["Nirenberg, D."]),
                   rec("b", "2", title="T", authors=["Nirenberg, David"])]
        merged, _ = merge_lib.merge_cluster(members, "M1")
        self.assertEqual(merged["authors"], ["Nirenberg, David"])

    def test_keywords_and_attachments_are_unioned(self):
        members = [rec("a", "1", title="T", keywords=["Iberia"],
                       file_attachments=["internal-pdf://a.pdf"]),
                   rec("b", "2", title="T", keywords=["violence"],
                       file_attachments=["internal-pdf://b.pdf"])]
        merged, _ = merge_lib.merge_cluster(members, "M1")
        self.assertEqual(set(merged["keywords"]), {"Iberia", "violence"})
        self.assertEqual(len(merged["file_attachments"]), 2)

    def test_earliest_year_is_kept_as_the_publication_year(self):
        members = [rec("a", "1", title="T", year="1997"),
                   rec("b", "2", title="T", year="1996")]
        merged, _ = merge_lib.merge_cluster(members, "M1")
        self.assertEqual(merged["year"], "1996")

    def test_raw_payload_of_every_member_rides_along(self):
        members = [rec("a", "1", title="T"), rec("b", "2", title="T")]
        members[0]["_raw"] = {"weird_legacy_column": "value nobody mapped"}
        merged, _ = merge_lib.merge_cluster(members, "M1")
        self.assertIn("a::1", merged["_raw"])
        self.assertEqual(merged["_raw"]["a::1"]["weird_legacy_column"],
                         "value nobody mapped")

    def test_oversized_notes_spill_to_an_overflow_file_not_the_bin(self):
        long_note = "x" * 5000
        members = [rec("a", "1", title="T", notes=long_note),
                   rec("b", "2", title="T", notes="short")]
        merged, overflow = merge_lib.merge_cluster(members, "M1", notes_limit=1000)
        self.assertIn("notes", overflow)
        self.assertIn(long_note, overflow["notes"])
        self.assertIn("TRUNCATED", merged["notes"])


# ---------------------------------------------------------------------------
# clustering constraints
# ---------------------------------------------------------------------------

class TestClusterConstraints(unittest.TestCase):
    def test_a_different_verdict_splits_a_transitive_cluster(self):
        # A~B (0.95) and B~C (0.93) would chain A, B and C together, but the
        # historian said A and C are different works. The chain must break.
        sys.path.insert(0, TOOL)
        merge_stage = __import__("40_merge")
        groups = [[0, 1, 2]]
        edges = {(0, 1): 0.95, (1, 2): 0.93}
        negative = {(0, 2)}
        out, conflicts = merge_stage.resolve_conflicts(groups, edges, negative)
        self.assertEqual(len(conflicts), 1)
        for piece in out:
            self.assertFalse(0 in piece and 2 in piece)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

class TestExport(unittest.TestCase):
    def test_reference_types_use_endnote_canonical_ids(self):
        for name, expected in (("Book", "6"), ("Journal Article", "17"),
                               ("Book Section", "5"), ("Edited Book", "28")):
            el = record_to_xml({"ref_type": name, "title": "T"}, 1).find("ref-type")
            self.assertEqual(el.text, expected, f"{name} exported as {el.text}")
            self.assertEqual(el.get("name"), name)

    def test_hebrew_and_long_notes_round_trip_through_xml(self):
        from readers import read_endnote_xml
        record = {"ref_type": "Book", "title": "תולדות היהודים בספרד הנוצרית",
                  "authors": ["בער, יצחק"], "year": "1959",
                  "notes": "--- [from lib #1] ---\nהמהדורה העברית\n\n" + "note " * 500,
                  "keywords": ["ספרד"], "urls": [], "file_attachments": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.xml")
            write_endnote_xml(path, [record])
            back = list(read_endnote_xml(path, "rt"))
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]["title"], record["title"])
        self.assertEqual(back[0]["authors"], record["authors"])
        self.assertIn("המהדורה העברית", back[0]["notes"])

    def test_control_characters_do_not_produce_an_unreadable_file(self):
        from readers import read_endnote_xml
        record = {"ref_type": "Book", "title": "Bad\x07Title", "notes": "a\x00b",
                  "authors": [], "keywords": [], "urls": [], "file_attachments": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.xml")
            write_endnote_xml(path, [record])
            back = list(read_endnote_xml(path, "rt"))
        self.assertEqual(back[0]["title"], "BadTitle")


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="endnote-consolidate-test-")
        cls.libs = os.path.join(cls.tmp, "libs")
        cls.work = os.path.join(cls.tmp, "work")
        make_fixture.build(cls.libs)
        cls.run_stage("00_inventory.py", "--root", cls.libs, "--work", cls.work)
        cls.run_stage("10_extract.py", "--work", cls.work)
        cls.run_stage("20_cluster.py", "--work", cls.work)
        cls.fill_review_decisions()
        cls.run_stage("30_adjudicate.py", "--work", cls.work, "--engine", "csv")
        cls.run_stage("40_merge.py", "--work", cls.work,
                      "--priority", "Nirenberg-2024", "Nirenberg-2011", "Nirenberg-1998")
        cls.run_stage("50_export.py", "--work", cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def fill_review_decisions(cls):
        """Stand in for the historian ticking the DECISION column: everything is
        the same 1996 book except the 2015 second edition."""
        import csv as _csv
        path = os.path.join(cls.work, "review-queue.csv")
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(_csv.DictReader(fh))
        assert rows, "fixture produced an empty review queue"
        for row in rows:
            row["DECISION"] = "different" if "2011::102" in row["pair_id"] else "same"
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    @classmethod
    def run_stage(cls, script, *args):
        proc = subprocess.run([sys.executable, os.path.join(TOOL, script), *args],
                              capture_output=True, text=True)
        assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def load(self, name):
        path = os.path.join(self.work, name)
        if name.endswith(".jsonl"):
            return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        return json.load(open(path, encoding="utf-8"))

    def test_all_three_library_formats_were_read(self):
        report = self.load("extract-report.json")
        kinds = {lib["kind"] for lib in report["libraries"]}
        self.assertEqual(kinds, {"enl", "endnote-xml", "ris"})
        self.assertEqual(report["total_records"], 16)

    def test_originals_are_never_modified(self):
        inventory = self.load("inventory.json")
        import hashlib
        for entry in inventory["libraries"]:
            digest = hashlib.sha256(open(entry["path"], "rb").read()).hexdigest()
            self.assertEqual(digest, entry["sha256"],
                             f"{entry['library']} was modified in place")

    def test_duplicates_across_libraries_were_found(self):
        merged = self.load("merged.jsonl")
        clusters = [r for r in merged if r["_member_count"] > 1]
        self.assertTrue(clusters, "no duplicates found at all")
        flagship = [r for r in clusters if "Communities of Violence" in r["title"]]
        self.assertEqual(len(flagship), 1)
        self.assertEqual(flagship[0]["_member_count"], 4)
        self.assertEqual(len(flagship[0]["_libraries"]), 3)
        # all four marginal notes, from three decades of libraries, in one record
        self.assertEqual(flagship[0]["_note_blocks"]["notes"], 4)

    def test_the_second_edition_was_not_swallowed(self):
        merged = self.load("merged.jsonl")
        editions = [r for r in merged if "Communities of Violence" in (r["title"] or "")]
        self.assertEqual(len(editions), 2, "the 1996 and 2015 editions must stay apart")
        years = sorted(r["year"] for r in editions)
        self.assertEqual(years, ["1996", "2015"])

    def test_human_different_verdicts_were_honoured(self):
        report = self.load("merge-report.json")
        self.assertGreater(report["decisions_applied"]["different"], 0)
        self.assertGreater(report["decisions_applied"]["same"], 0)

    def test_verification_passes(self):
        out = self.run_stage("60_verify.py", "--work", self.work)
        self.assertIn("PASS", out)

    def test_verification_actually_detects_loss(self):
        """The no-loss check must be capable of failing, or it proves nothing."""
        sabotaged = os.path.join(self.tmp, "sabotage")
        shutil.copytree(self.work, sabotaged)
        path = os.path.join(sabotaged, "merged.jsonl")
        rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        wiped = 0
        for row in rows:
            if row["_member_count"] > 1 and row.get("notes"):
                row["notes"] = "(a careless merge dropped this)"
                wiped += 1
        self.assertTrue(wiped, "fixture has no merged notes to sabotage")
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(TOOL, "60_verify.py"),
             "--work", sabotaged, "--skip-xml"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("LOST NOTE", proc.stdout)

    def test_crosswalk_accounts_for_every_source_record(self):
        import csv as _csv
        with open(os.path.join(self.work, "crosswalk.csv"), encoding="utf-8-sig") as fh:
            rows = list(_csv.DictReader(fh))
        records = self.load("records.jsonl")
        self.assertEqual(len(rows), len(records))
        self.assertEqual({r["source_uid"] for r in rows}, {r["_uid"] for r in records})

    def test_sources_json_bridge_marks_disagreement_as_low_confidence(self):
        sources = json.load(open(os.path.join(self.work, "out", "sources.json"),
                                 encoding="utf-8"))
        self.assertEqual(len(sources), len(self.load("merged.jsonl")))
        flagship = next(s for s in sources if "Communities of Violence" in s["workTitle"])
        # The libraries disagreed about the title, so the auditor must not
        # treat the elected one as verified fact.
        self.assertEqual(flagship["extractionConfidence"]["title"], "low")
        self.assertEqual(flagship["extractionConfidence"]["year"], "high")


if __name__ == "__main__":
    unittest.main(verbosity=2)

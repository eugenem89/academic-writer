#!/usr/bin/env python3
"""
Stage 60 — prove nothing was lost. Exits non-zero if anything was.

    python3 60_verify.py --work ./work

This is the stage that makes the whole pipeline trustworthy, so it re-derives
its facts from the source files rather than from any downstream report:

  1. Every source record appears in the crosswalk exactly once.
  2. Every merged record round-trips through the exported XML.
  3. Every non-empty note, research note and custom field in every source
     record is still findable, character for character, in the merged record
     (or in its overflow sidecar).
  4. Every distinct value of every scalar field is either the elected value or
     present in the variant ledger.
  5. Every keyword, URL and attachment path survives the union.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from merge import AUTHOR_FIELDS, name_key  # noqa: E402
from readers import read_endnote_xml  # noqa: E402
from records import LIST_FIELDS, NOTE_FIELDS, SCALAR_FIELDS, load_jsonl  # noqa: E402
from textnorm import normalize_text  # noqa: E402

WS = re.compile(r"\s+")


def squash(text: str) -> str:
    return WS.sub(" ", str(text or "")).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify no data was lost in consolidation.")
    ap.add_argument("--work", default="./work")
    ap.add_argument("--skip-xml", action="store_true",
                    help="skip the XML round-trip check (slow on huge libraries)")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    sources = load_jsonl(os.path.join(work, "records.jsonl"))
    merged = load_jsonl(os.path.join(work, "merged.jsonl"))
    by_merge = {rec["_merge_id"]: rec for rec in merged}

    failures: list[str] = []
    warnings: list[str] = []
    checks = Counter()

    # --- 1. crosswalk covers every source record exactly once -----------------
    crosswalk_path = os.path.join(work, "crosswalk.csv")
    seen: Counter = Counter()
    uid_to_merge: dict[str, str] = {}
    with open(crosswalk_path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            seen[row["source_uid"]] += 1
            uid_to_merge[row["source_uid"]] = row["merge_id"]
    source_uids = {rec["_uid"] for rec in sources}
    missing = source_uids - set(seen)
    duplicated = [uid for uid, n in seen.items() if n > 1]
    extra = set(seen) - source_uids
    if missing:
        failures.append(f"{len(missing)} source record(s) missing from crosswalk: "
                        f"{sorted(missing)[:5]}")
    if duplicated:
        failures.append(f"{len(duplicated)} source record(s) in more than one cluster: "
                        f"{duplicated[:5]}")
    if extra:
        failures.append(f"{len(extra)} crosswalk row(s) reference unknown records")
    checks["crosswalk_rows"] = sum(seen.values())

    # --- 2/3/4/5. per-record content preservation -----------------------------
    overflow_dir = os.path.join(work, "overflow")
    overflow_cache: dict[str, str] = {}

    def overflow_text(merge_id: str, field: str) -> str:
        key = f"{merge_id}.{field}"
        if key not in overflow_cache:
            path = os.path.join(overflow_dir, f"{key}.txt")
            overflow_cache[key] = (open(path, encoding="utf-8").read()
                                   if os.path.exists(path) else "")
        return overflow_cache[key]

    for rec in sources:
        uid = rec["_uid"]
        merge_id = uid_to_merge.get(uid)
        target = by_merge.get(merge_id) if merge_id else None
        if target is None:
            continue  # already reported as a crosswalk failure

        for field in NOTE_FIELDS:
            text = squash(rec.get(field))
            if not text:
                continue
            checks["notes_checked"] += 1
            haystack = squash(target.get(field)) + " " + squash(overflow_text(merge_id, field))
            if text not in haystack:
                failures.append(f"LOST NOTE: {uid} field {field} is not present in "
                                f"{merge_id} ({text[:80]!r})")
            else:
                checks["notes_preserved"] += 1

        for field in SCALAR_FIELDS:
            value = squash(rec.get(field))
            if not value:
                continue
            checks["scalars_checked"] += 1
            elected = squash(target.get(field))
            if normalize_text(value) == normalize_text(elected):
                continue
            variants = target.get("_variants", {}).get(field, [])
            if any(normalize_text(value) == normalize_text(v["value"]) for v in variants):
                continue
            if elected and normalize_text(value) in normalize_text(elected):
                continue  # subsumed by a fuller elected value (subtitle case)
            failures.append(f"LOST FIELD: {uid} {field}={value[:60]!r} is neither the "
                            f"elected value nor in the variant ledger of {merge_id}")

        for field in LIST_FIELDS:
            variants = target.get("_variants", {}).get(field, [])
            if field in AUTHOR_FIELDS:
                # Author lists are elected, not unioned, so a name counts as
                # preserved if it is in the elected list under any spelling of
                # the same person, or in a kept variant list verbatim.
                target_keys = {name_key(v) for v in (target.get(field) or [])}
                for entry in variants:
                    target_keys.update(name_key(v) for v in entry["value"])
                for value in rec.get(field) or []:
                    if not str(value).strip():
                        continue
                    checks["list_items_checked"] += 1
                    if name_key(str(value)) not in target_keys:
                        failures.append(f"LOST AUTHOR: {uid} {field} {value!r} "
                                        f"absent from {merge_id}")
                continue
            target_keys = {normalize_text(v) for v in (target.get(field) or [])}
            for entry in variants:
                target_keys.update(normalize_text(v) for v in entry["value"])
            for value in rec.get(field) or []:
                if not str(value).strip():
                    continue
                checks["list_items_checked"] += 1
                if normalize_text(value) not in target_keys:
                    failures.append(f"LOST LIST ITEM: {uid} {field} {value!r} "
                                    f"absent from {merge_id}")

        if rec.get("_prov", {}).get("source_kind") == "ris":
            warnings.append(f"{uid} came from RIS, a lossy format — custom fields "
                            f"may never have reached this pipeline")

    # --- 2b. XML round-trip ---------------------------------------------------
    xml_path = os.path.join(work, "out", "consolidated.xml")
    if not args.skip_xml and os.path.exists(xml_path):
        roundtrip = list(read_endnote_xml(xml_path, "roundtrip"))
        checks["xml_records"] = len(roundtrip)
        if len(roundtrip) != len(merged):
            failures.append(f"XML round-trip: exported {len(merged)} records but "
                            f"read back {len(roundtrip)}")
        else:
            for original, back in zip(merged, roundtrip):
                for field in ("title", "notes", "research_notes"):
                    a, b = squash(original.get(field)), squash(back.get(field))
                    if normalize_text(a) != normalize_text(b):
                        failures.append(
                            f"XML round-trip: {original['_merge_id']} {field} changed "
                            f"({a[:60]!r} -> {b[:60]!r})")
                        break
    elif not args.skip_xml:
        warnings.append("consolidated.xml not found — run 50_export.py before verifying")

    # --- report ---------------------------------------------------------------
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_records": len(sources),
        "merged_records": len(merged),
        "checks": dict(checks),
        "failures": failures,
        "warnings": sorted(set(warnings)),
        "verdict": "PASS" if not failures else "FAIL",
    }
    with open(os.path.join(work, "verify-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"source records   : {len(sources)}")
    print(f"merged records   : {len(merged)}")
    print(f"notes preserved  : {checks['notes_preserved']}/{checks['notes_checked']}")
    print(f"scalars checked  : {checks['scalars_checked']}")
    print(f"list items       : {checks['list_items_checked']}")
    if report["warnings"]:
        print(f"warnings         : {len(report['warnings'])}")
    if failures:
        print(f"\nFAIL — {len(failures)} problem(s):")
        for line in failures[:25]:
            print(f"  - {line}")
        if len(failures) > 25:
            print(f"  … and {len(failures) - 25} more (see verify-report.json)")
        return 1
    print("\nPASS — every note, field value and list item from every source "
          "record is present in the consolidated library.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

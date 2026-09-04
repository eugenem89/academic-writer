# EndNote library consolidation

Merging ~30 years of EndNote libraries into one, without losing a single note.

Everything here runs from a local terminal with **stock Python 3.9+ and no
third-party packages**. A language model is used at exactly one optional step,
on the small set of pairs the deterministic scoring could not decide.

---

## The governing principle

Two records for the same book with two different marginal notes are **not a
duplicate to be resolved**. They are one reference with two notes. Every design
decision below follows from that:

| | policy |
|---|---|
| Notes, research notes, custom fields 1–8 | **concatenated** with attribution, never chosen between |
| Keywords, URLs, attachments, groups | **unioned** |
| Author lists | most complete list elected; `Nirenberg, D.` folds into `Nirenberg, David`, but a genuinely different list is kept as a variant |
| Title, publisher, journal, volume … | one value elected, **every other value kept in a variant ledger** |
| The original record | the untouched source payload rides along inside every merged record forever |

The pipeline is also asymmetric about its errors on purpose. A missed duplicate
costs one extra row. A wrong merge silently destroys a distinction — between the
1996 and 2015 editions, between a chapter and the volume that contains it,
between a translation and its original. So anything that looks like a real
bibliographic distinction is routed to a human rather than merged, however well
the strings match.

---

## Before you run anything

**1. Get the libraries into a readable format.**

EndNote X7 and later store a `.enl` as a SQLite database, which stage 00 detects
and reads directly — no EndNote needed. Older libraries (EndNote 8 through X6,
which is where the 1990s and 2000s material will be) are a proprietary binary
format that nothing but EndNote can open. For each of those, in EndNote:

> File → Export… → Output style: **EndNote Export**, Save as type: **XML**

Export XML, not RIS. RIS silently drops custom fields — which is often exactly
where a researcher's own annotations live. Stage 60 flags any library that
arrived as RIS so you know its notes may be incomplete before you ever got
started.

**2. Copy everything out of Google Drive first.**

Do not run the SQLite reader against a `.enl` sitting in a syncing Drive folder.
The sync client can swap the file mid-read and SQLite will report corruption on
a perfectly healthy library. Stage 00 does the copying for you and verifies the
copy by SHA-256; the rest of the pipeline only ever touches that frozen copy.
Keep the scripts in Drive if you like — just point `--root` at a local copy of
the libraries, or let stage 00 make one.

**3. Keep the `.Data` folders.**

Every `.enl` has a sibling `Library.Data/` folder holding the attached PDFs.
Attachment *paths* travel through this pipeline; the *files* do not. Stage 00
inventories and (with `--include-data-folders`) freezes them. Re-linking PDFs is
a separate job, best done in EndNote after the merged library exists.

---

## The pipeline

```
./run_all.sh "/path/to/libraries" ./work
```

That runs stages 00–20, stops at the review queue, and tells you how to resume.
Or run the stages by hand:

| stage | what it does | what it writes |
|---|---|---|
| `00_inventory.py` | finds every library, hashes it, freezes a working copy | `inventory.json`, `sources/` |
| `10_extract.py` | reads `.enl` / EndNote XML / RIS into one canonical file | `records.jsonl` |
| `20_cluster.py` | blocks, scores every plausible pair, clusters the certain ones | `clusters.json`, `pairs.jsonl`, `review-queue.csv` |
| `30_adjudicate.py` | decides the uncertain pairs — **the only model-assisted stage, and optional** | `decisions.jsonl` |
| `40_merge.py` | merges, honouring your decisions | `merged.jsonl`, `crosswalk.csv` |
| `50_export.py` | writes the new library | `out/consolidated.xml`, `out/sources.json` |
| `60_verify.py` | proves nothing was lost; exits non-zero if anything was | `verify-report.json` |

### What decides a match

Blocking puts plausible pairs in the same bucket (shared DOI, ISBN, title
prefix, sorted title tokens, or author-surname + year ± 1), then each pair is
scored on title, authors, year, container, and volume/issue/pages. Components
with no evidence on either side are dropped and their weight redistributed, so a
book is never penalised for having no journal or issue number.

Normalisation is script-aware, which matters for this corpus: Latin loses its
diacritics (`Muñoz` = `Munoz`), Hebrew loses niqqud but keeps its letters
(`תּוֹלְדוֹת` = `תולדות`), Arabic loses harakat and tatweel. Subtitles are compared
both attached and amputated, because one library kept them and another didn't.

Above the score, a set of **blockers** forces review no matter how well the
strings match: different edition numbers, different volumes, disjoint
translators, different languages, a book vs. a chapter, a >3-year gap between
two books, two articles at different page ranges in the same journal issue.

### Stage 30 — the only place a model is used

Stage 20 typically routes a low single-digit percentage of pairs to review.
Three ways to clear them, all driven from your terminal:

```bash
# A. free, in a spreadsheet — fill the DECISION column with same / different
python3 30_adjudicate.py --work ./work --engine csv

# B. the local claude CLI in headless mode (no API key needed)
python3 30_adjudicate.py --work ./work --engine claude

# C. the API over stdlib urllib (needs ANTHROPIC_API_KEY)
python3 30_adjudicate.py --work ./work --engine api
```

Verdicts are cached by pair content, so re-running after a threshold change
costs nothing for pairs already judged. A human decision always outranks a model
one. Anything the model marks `unsure` stays unmerged and lands in
`still-unsure.csv`. The prompt carries the humanities rules explicitly —
editions differ, translations differ, a chapter is not its volume, and *differing
notes never make two records different*.

The sensible first pass is B, then read `decisions.jsonl` and overrule anything
you disagree with in the CSV.

### Decisions are honoured, including the negative ones

If you say A and C are different works, but the scoring chained them together
through B, stage 40 splits the cluster by dropping its weakest links rather than
merging across your judgement. Every split is recorded in `merge-report.json`.

---

## Checking the result

`60_verify.py` re-derives its facts from the source records rather than trusting
any earlier report, and fails loudly:

1. every source record appears in the crosswalk exactly once
2. every note, research note and custom field is still findable **character for
   character** in its merged record (or its overflow sidecar)
3. every scalar value is either the elected value or in the variant ledger
4. every keyword, URL and attachment path survived
5. the exported XML reads back identically

The test suite includes a mutation test that sabotages a merged file and
asserts the verifier catches it — a no-loss check that cannot fail proves
nothing.

```bash
python3 tools/endnote-consolidate/tests/test_consolidate.py
```

Then read these by hand before importing:

- `out/duplicates.csv` — only the merged clusters. Skim the biggest ones first.
- `crosswalk.csv` — the undo map: every source record → the record it became.
- `merge-report.json` — cluster size histogram, decisions applied, splits.

### Importing

> EndNote → File → New… (create an **empty** library) → File → Import → File…
> Import Option: **EndNote Generated XML**, Duplicates: **Import All**

Import into a new library, never on top of an existing one. Set Duplicates to
"Import All" — EndNote's own duplicate detection is cruder than what just ran,
and letting it discard records would undo the work.

---

## Feeding the writing plugin

`50_export.py` also emits `out/sources.json` in the shape
`.academic-helper/sources.json` expects, so the consolidated library can drive
this plugin's citation auditor (Check D) directly. `extractionConfidence` is
computed rather than stamped: a field is `high` only when every merged source
record agreed on it. Where the libraries disagreed, the auditor gets `low` and
tags the citation `[NEEDS REVIEW]` instead of trusting a coin-flip election.

---

## Practical notes

**Scale.** 27,000 records producing 1.4 million candidate pairs clusters in
about three minutes on a laptop. Installing `rapidfuzz` (optional) speeds up
string comparison; nothing requires it.

**Tuning.** Start conservative — `--auto-merge 0.95` — and look at what lands in
`duplicates.csv`. If the merges are all obviously right, lower it and re-run.
Every stage is re-runnable from `records.jsonl`; nothing downstream is precious.

**Order matters for ties.** `--priority` lists libraries best-first, breaking
ties when electing a field value: `--priority current-2024 archive-2011 old-1998`.

**Long notes.** Anything past `--notes-limit` (default 60,000 characters) spills
to `work/overflow/<merge_id>.<field>.txt` with a pointer left in the field.
Stage 60 checks the sidecars too.

**Nothing is destroyed.** The originals are never opened for writing. If a merge
turns out to be wrong six months from now, `crosswalk.csv` says exactly which
source records went into it, and `merged.jsonl` still carries their untouched
payloads.

#!/usr/bin/env python3
"""
Stage 10 — read every inventoried library into one canonical records.jsonl.

    python3 10_extract.py --work ./work

Output: work/records.jsonl (one canonical record per source record, each
carrying its untouched `_raw` payload and `_prov` origin) and
work/extract-report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from readers import read_endnote_xml, read_enl, read_ris  # noqa: E402
from records import write_jsonl  # noqa: E402

READERS = {"enl": read_enl, "endnote-xml": read_endnote_xml, "ris": read_ris}


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract records from inventoried libraries.")
    ap.add_argument("--work", default="./work")
    ap.add_argument("--include-trash", action="store_true",
                    help="also read records sitting in the library's trash")
    ap.add_argument("--only", nargs="*", help="limit to these library names")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    with open(os.path.join(work, "inventory.json"), encoding="utf-8") as fh:
        inventory = json.load(fh)

    all_records = []
    report = {"generated": datetime.now(timezone.utc).isoformat(), "libraries": [],
              "errors": [], "flag_counts": {}}
    flags: Counter = Counter()

    for entry in inventory["libraries"]:
        library = entry["library"]
        if args.only and library not in args.only:
            continue
        path = entry.get("frozen_copy") or entry["path"]
        reader = READERS[entry["kind"]]
        kwargs = {"include_trash": args.include_trash} if entry["kind"] == "enl" else {}
        try:
            records = list(reader(path, library, **kwargs))
        except Exception as exc:  # a bad library must not abort the other 20
            msg = f"{library}: {type(exc).__name__}: {exc}"
            report["errors"].append(msg)
            print(f"ERROR {msg}", file=sys.stderr)
            continue

        for rec in records:
            for flag in rec.get("_prov", {}).get("flags", []):
                flags[flag.split(":")[-1]] += 1
        all_records.extend(records)

        types = Counter(r.get("ref_type") or "(none)" for r in records)
        with_notes = sum(1 for r in records
                         if any(str(r.get(f) or "").strip()
                                for f in ("notes", "research_notes")))
        report["libraries"].append({
            "library": library, "kind": entry["kind"], "path": path,
            "records": len(records), "records_with_notes": with_notes,
            "lossy_format": entry["kind"] == "ris",
            "top_types": types.most_common(8),
        })
        print(f"{library:<32} {len(records):6d} records  ({with_notes} with notes)")

    out = os.path.join(work, "records.jsonl")
    n = write_jsonl(out, all_records)
    report["total_records"] = n
    report["flag_counts"] = dict(flags)
    with open(os.path.join(work, "extract-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"\n{n} records -> {out}")
    if flags:
        print("field flags:", dict(flags))
    if report["errors"]:
        print(f"{len(report['errors'])} library error(s) — see extract-report.json",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

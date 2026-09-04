#!/usr/bin/env python3
"""
Stage 50 — write the consolidated library out.

    python3 50_export.py --work ./work

Produces:
  work/out/consolidated.xml    EndNote XML — import into a NEW empty library
  work/out/consolidated.csv    the same thing in a spreadsheet, for eyeballing
  work/out/sources.json        the academic-writer citation registry shape
  work/out/duplicates.csv      only the merged clusters, for spot-checking

To import: EndNote > File > New… (make an empty library) > File > Import >
File…, Import Option: "EndNote Generated XML", Duplicates: "Import All".
Import into a NEW library, never on top of an existing one.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from records import load_jsonl  # noqa: E402
from writers import to_sources_json, write_csv, write_endnote_xml, write_json  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Export the consolidated library.")
    ap.add_argument("--work", default="./work")
    ap.add_argument("--out", help="output directory (default work/out)")
    ap.add_argument("--variants-to", choices=[f"custom{i}" for i in range(1, 9)],
                    help="also write the field-variant ledger into this EndNote "
                         "custom field, so disagreements are visible in EndNote itself")
    ap.add_argument("--no-sources-json", action="store_true")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(work, "out")
    os.makedirs(out_dir, exist_ok=True)

    merged = load_jsonl(os.path.join(work, "merged.jsonl"))

    if args.variants_to:
        for rec in merged:
            variants = rec.get("_variants", {})
            if not variants:
                continue
            lines = []
            for field, entries in sorted(variants.items()):
                for entry in entries[1:]:  # entry 0 is the elected value
                    lines.append(f"{field}: {entry['value']}  [{', '.join(entry['from'])}]")
            if lines:
                existing = rec.get(args.variants_to) or ""
                rec[args.variants_to] = (
                    (existing + "\n\n" if existing else "")
                    + "--- [variant field values from merged records] ---\n"
                    + "\n".join(lines))

    xml_path = os.path.join(out_dir, "consolidated.xml")
    n = write_endnote_xml(xml_path, merged)
    csv_path = os.path.join(out_dir, "consolidated.csv")
    write_csv(csv_path, merged)

    dupes = [r for r in merged if r.get("_member_count", 1) > 1]
    write_csv(os.path.join(out_dir, "duplicates.csv"), dupes)

    print(f"{n} records -> {xml_path}")
    print(f"{n} rows     -> {csv_path}")
    print(f"{len(dupes)} merged cluster(s) -> {os.path.join(out_dir, 'duplicates.csv')}")

    if not args.no_sources_json:
        sources_path = os.path.join(out_dir, "sources.json")
        write_json(sources_path, to_sources_json(merged))
        print(f"{n} entries -> {sources_path}  "
              f"(copy to .academic-helper/sources.json to feed the citation auditor)")

    print("\nImport: EndNote > File > New… (empty library) > File > Import > File…")
    print('        Import Option: "EndNote Generated XML"   Duplicates: "Import All"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

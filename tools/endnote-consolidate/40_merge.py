#!/usr/bin/env python3
"""
Stage 40 — apply decisions, re-cluster, and merge.

    python3 40_merge.py --work ./work

Adds "same" decisions as merge edges, and honours "different" decisions as
*negative constraints*: if a decided-different pair ends up in the same cluster
through a chain of other matches (A~B, B~C, but A and C were judged different),
the cluster is split by dropping its weakest edges until the constraint holds.
Silently merging across a human's "different" would defeat the point of asking.

Outputs:
  work/merged.jsonl        one record per consolidated reference
  work/crosswalk.csv       every source record -> its merged record (the undo map)
  work/overflow/*.txt      note text too long for an EndNote field
  work/merge-report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import match  # noqa: E402
from merge import merge_cluster  # noqa: E402
from records import load_jsonl, write_jsonl  # noqa: E402

# EndNote fields hold a lot but not an unbounded amount; spill past this into a
# sidecar file rather than silently truncating a researcher's marginalia.
DEFAULT_NOTES_LIMIT = 60000


def resolve_conflicts(groups: list[list[int]], edges: dict[tuple[int, int], float],
                      negative: set[tuple[int, int]]) -> tuple[list[list[int]], list[dict]]:
    """Greedily drop the weakest edges until no cluster contains a negative pair."""
    out: list[list[int]] = []
    conflicts: list[dict] = []
    for group in groups:
        members = set(group)
        bad = [(a, b) for (a, b) in negative if a in members and b in members]
        if not bad or len(group) == 1:
            out.append(group)
            continue
        local = {e: w for e, w in edges.items() if e[0] in members and e[1] in members}
        dropped = []
        while bad and local:
            weakest = min(local, key=lambda e: local[e])
            dropped.append(weakest)
            del local[weakest]
            sub = match.cluster(max(members) + 1, list(local))
            pieces = [[i for i in piece if i in members] for piece in sub]
            pieces = [p for p in pieces if p]
            bad = [(a, b) for (a, b) in negative
                   for piece in pieces if a in piece and b in piece]
        sub = match.cluster(max(members) + 1, list(local))
        pieces = [sorted(i for i in piece if i in members) for piece in sub]
        pieces = [p for p in pieces if p]
        conflicts.append({"original_members": sorted(members),
                          "dropped_edges": [list(e) for e in dropped],
                          "split_into": pieces})
        out.extend(pieces)
    return out, conflicts


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge clustered duplicate references.")
    ap.add_argument("--work", default="./work")
    ap.add_argument("--priority", nargs="*", default=[],
                    help="library names, best first — breaks ties when electing "
                         "a field value (e.g. --priority current-2024 archive-2010)")
    ap.add_argument("--notes-limit", type=int, default=DEFAULT_NOTES_LIMIT)
    ap.add_argument("--allow-conflicts", action="store_true",
                    help="keep clusters that violate a 'different' decision "
                         "(default is to split them)")
    ap.add_argument("--min-confidence", type=float, default=0.0,
                    help="ignore model verdicts below this confidence")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    records = load_jsonl(os.path.join(work, "records.jsonl"))
    index = {rec["_uid"]: i for i, rec in enumerate(records)}

    pairs = load_jsonl(os.path.join(work, "pairs.jsonl"))
    edges: dict[tuple[int, int], float] = {}
    merge_pairs: list[tuple[int, int]] = []
    for row in pairs:
        if row["a"] not in index or row["b"] not in index:
            continue
        key = (index[row["a"]], index[row["b"]])
        edges[key] = row["score"]
        if row["decision"] == "auto_merge":
            merge_pairs.append(key)

    decisions_path = os.path.join(work, "decisions.jsonl")
    decisions = load_jsonl(decisions_path) if os.path.exists(decisions_path) else []
    negative: set[tuple[int, int]] = set()
    applied = {"same": 0, "different": 0, "unsure": 0, "skipped": 0}
    for d in decisions:
        a_uid, _, b_uid = d["pair_id"].partition("|")
        if a_uid not in index or b_uid not in index:
            applied["skipped"] += 1
            continue
        if d.get("source", "").startswith(("claude", "api")) and \
                float(d.get("confidence", 0)) < args.min_confidence:
            applied["skipped"] += 1
            continue
        key = (index[a_uid], index[b_uid])
        if d["verdict"] == "same":
            merge_pairs.append(key)
            edges.setdefault(key, 1.0)
            applied["same"] += 1
        elif d["verdict"] == "different":
            negative.add(key)
            applied["different"] += 1
        else:
            applied["unsure"] += 1

    groups = match.cluster(len(records), merge_pairs)
    conflicts: list[dict] = []
    if negative and not args.allow_conflicts:
        groups, conflicts = resolve_conflicts(groups, edges, negative)

    priority = {name: len(args.priority) - i for i, name in enumerate(args.priority)}
    overflow_dir = os.path.join(work, "overflow")
    merged_records, crosswalk = [], []
    overflow_files = 0

    for i, group in enumerate(sorted(groups, key=lambda g: g[0]), start=1):
        merge_id = f"M{i:06d}"
        members = [records[j] for j in group]
        merged, overflow = merge_cluster(members, merge_id, priority=priority,
                                         notes_limit=args.notes_limit)
        for field, text in overflow.items():
            os.makedirs(overflow_dir, exist_ok=True)
            with open(os.path.join(overflow_dir, f"{merge_id}.{field}.txt"),
                      "w", encoding="utf-8") as fh:
                fh.write(text)
            overflow_files += 1
        merged_records.append(merged)
        for rec in members:
            crosswalk.append({
                "merge_id": merge_id,
                "source_uid": rec["_uid"],
                "library": rec["_prov"].get("library", ""),
                "source_record_id": rec["_prov"].get("record_id", ""),
                "source_file": rec["_prov"].get("source_file", ""),
                "fingerprint": rec.get("_fingerprint", ""),
                "cluster_size": len(members),
                "title_as_recorded": rec.get("title", ""),
            })

    write_jsonl(os.path.join(work, "merged.jsonl"), merged_records)
    with open(os.path.join(work, "crosswalk.csv"), "w", encoding="utf-8-sig",
              newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(crosswalk[0].keys()) if crosswalk
                                else ["merge_id", "source_uid"])
        writer.writeheader()
        writer.writerows(crosswalk)

    by_size: dict[int, int] = defaultdict(int)
    for rec in merged_records:
        by_size[rec["_member_count"]] += 1
    notes_preserved = sum(sum(rec.get("_note_blocks", {}).values()) for rec in merged_records)
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_records": len(records),
        "merged_records": len(merged_records),
        "records_absorbed": len(records) - len(merged_records),
        "cluster_size_histogram": {str(k): v for k, v in sorted(by_size.items())},
        "decisions_applied": applied,
        "negative_constraints": len(negative),
        "conflicts_split": conflicts,
        "distinct_note_blocks_preserved": notes_preserved,
        "overflow_files": overflow_files,
        "priority_order": args.priority,
    }
    with open(os.path.join(work, "merge-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"{len(records)} source records -> {len(merged_records)} merged "
          f"({len(records) - len(merged_records)} absorbed)")
    print(f"decisions applied: {applied}")
    print(f"distinct note blocks preserved: {notes_preserved}")
    if conflicts:
        print(f"{len(conflicts)} cluster(s) split to honour a 'different' decision")
    if overflow_files:
        print(f"{overflow_files} oversized note(s) spilled to work/overflow/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

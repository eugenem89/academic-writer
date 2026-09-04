#!/usr/bin/env python3
"""
Stage 20 — find duplicate clusters.

    python3 20_cluster.py --work ./work [--config config.json]

Outputs:
  work/pairs.jsonl        every scored candidate pair (the full audit trail)
  work/clusters.json      auto-merge clusters
  work/review-queue.jsonl pairs a human (or stage 30) must decide
  work/review-queue.csv    the same, as a spreadsheet with a DECISION column
  work/cluster-report.json counts, threshold settings, oversized blocks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import match  # noqa: E402
from records import load_jsonl, write_jsonl  # noqa: E402
from writers import write_csv  # noqa: E402


def brief(rec: dict) -> dict:
    authors = rec.get("authors") or rec.get("secondary_authors") or []
    return {
        "uid": rec.get("_uid"), "library": rec.get("_prov", {}).get("library"),
        "ref_type": rec.get("ref_type"), "authors": "; ".join(map(str, authors[:4])),
        "year": rec.get("year"), "title": rec.get("title"),
        "container": rec.get("secondary_title"), "publisher": rec.get("publisher"),
        "volume": rec.get("volume"), "issue": rec.get("issue"),
        "pages": rec.get("pages"), "edition": rec.get("edition"),
        "doi": rec.get("doi"), "isbn": rec.get("isbn"),
        "notes": (rec.get("notes") or "")[:400],
        "research_notes": (rec.get("research_notes") or "")[:400],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Cluster duplicate references.")
    ap.add_argument("--work", default="./work")
    ap.add_argument("--config", help="JSON config overriding thresholds/weights")
    ap.add_argument("--auto-merge", type=float, help="override auto_merge threshold")
    ap.add_argument("--review-low", type=float, help="override review_low threshold")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    cfg = dict(match.DEFAULT_THRESHOLDS)
    cfg["weights"] = dict(match.DEFAULT_WEIGHTS)
    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            user = json.load(fh)
        cfg.update(user.get("thresholds", {}))
        cfg["weights"].update(user.get("weights", {}))
    if args.auto_merge is not None:
        cfg["auto_merge"] = args.auto_merge
    if args.review_low is not None:
        cfg["review_low"] = args.review_low

    records = load_jsonl(os.path.join(work, "records.jsonl"))
    print(f"{len(records)} records loaded")
    match.prepare(records)      # normalise every record once, not once per pair

    pairs, oversized = match.candidate_pairs(records, cfg)
    print(f"{len(pairs)} candidate pairs from blocking")

    scored, merge_pairs, review = [], [], []
    for a_idx, b_idx in sorted(pairs):
        result = match.score_pair(records[a_idx], records[b_idx], cfg)
        row = {"a": records[a_idx]["_uid"], "b": records[b_idx]["_uid"], **result}
        if result["score"] >= cfg["auto_merge"] and not result["blockers"]:
            row["decision"] = "auto_merge"
            merge_pairs.append((a_idx, b_idx))
        elif result["score"] >= cfg["review_low"]:
            row["decision"] = "review"
            review.append({**row, "a_record": brief(records[a_idx]),
                           "b_record": brief(records[b_idx])})
        else:
            row["decision"] = "distinct"
        scored.append(row)

    write_jsonl(os.path.join(work, "pairs.jsonl"), scored)
    write_jsonl(os.path.join(work, "review-queue.jsonl"), review)

    flat = []
    for row in review:
        flat.append({
            "pair_id": f"{row['a']}|{row['b']}",
            "score": row["score"],
            "blockers": "; ".join(row["blockers"]),
            "reasons": "; ".join(row["reasons"]),
            "DECISION": "",  # fill in with same / different / unsure
            "a_uid": row["a"], "a_authors": row["a_record"]["authors"],
            "a_year": row["a_record"]["year"], "a_title": row["a_record"]["title"],
            "a_container": row["a_record"]["container"],
            "a_edition": row["a_record"]["edition"], "a_notes": row["a_record"]["notes"],
            "b_uid": row["b"], "b_authors": row["b_record"]["authors"],
            "b_year": row["b_record"]["year"], "b_title": row["b_record"]["title"],
            "b_container": row["b_record"]["container"],
            "b_edition": row["b_record"]["edition"], "b_notes": row["b_record"]["notes"],
        })
    write_csv(os.path.join(work, "review-queue.csv"), flat,
              columns=list(flat[0].keys()) if flat else ["pair_id", "DECISION"])

    clusters = match.cluster(len(records), merge_pairs)
    named = []
    for i, group in enumerate(clusters, start=1):
        named.append({"merge_id": f"M{i:06d}",
                      "members": [records[j]["_uid"] for j in group]})
    with open(os.path.join(work, "clusters.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(),
                   "config": cfg, "clusters": named}, fh, ensure_ascii=False, indent=2)

    multi = [c for c in named if len(c["members"]) > 1]
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "config": cfg,
        "records": len(records),
        "candidate_pairs": len(pairs),
        "auto_merge_pairs": len(merge_pairs),
        "review_pairs": len(review),
        "clusters": len(named),
        "clusters_with_duplicates": len(multi),
        "records_absorbed": sum(len(c["members"]) - 1 for c in multi),
        "largest_cluster": max((len(c["members"]) for c in named), default=0),
        "oversized_blocks_skipped": oversized,
    }
    with open(os.path.join(work, "cluster-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"auto-merge pairs : {len(merge_pairs)}")
    print(f"review pairs     : {len(review)}  -> review-queue.csv")
    print(f"clusters         : {len(named)} ({len(multi)} contain duplicates, "
          f"{report['records_absorbed']} records absorbed)")
    if oversized:
        print(f"WARNING: {len(oversized)} oversized block(s) skipped; "
              f"duplicates inside them will be missed. See cluster-report.json.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

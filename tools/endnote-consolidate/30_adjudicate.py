#!/usr/bin/env python3
"""
Stage 30 — decide the pairs the scoring could not decide. OPTIONAL.

This is the only stage in the pipeline that uses a language model, and it only
ever sees the pairs stage 20 routed to review — typically a low single-digit
percentage of the corpus. Everything else is deterministic Python.

Three engines, all driven from a local terminal:

  --engine csv     you fill the DECISION column in work/review-queue.csv       (free)
  --engine claude  shells out to the local `claude` CLI in headless mode       (no key needed)
  --engine api     calls the Messages API over stdlib urllib (ANTHROPIC_API_KEY)

Results are cached by pair content hash in work/adjudication-cache.json, so
re-running after a threshold change costs nothing for pairs already judged.
All engines write the same work/decisions.jsonl.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from records import load_jsonl, write_jsonl  # noqa: E402

DEFAULT_MODEL = "claude-opus-5"

SYSTEM = """You are helping a historian consolidate 30 years of EndNote \
libraries. For each pair of bibliographic records, decide whether they are the \
SAME work recorded twice, or DIFFERENT works.

Rules that matter in humanities scholarship:
- Different EDITIONS of a book are DIFFERENT records. Page numbers differ, so \
citations break if they are merged.
- Different TRANSLATIONS, or a translation vs. its original, are DIFFERENT.
- A book CHAPTER and the EDITED VOLUME containing it are DIFFERENT.
- Different VOLUMES of a multi-volume work are DIFFERENT.
- A reprint or a later paperback with its own year is DIFFERENT unless the \
record is plainly the same publication with a sloppier date.
- The SAME work catalogued with a fuller title, a corrected name spelling, an \
added subtitle, a transliteration difference, a missing subtitle, or one \
library's abbreviated journal name is the SAME.
- Two records for the same work carrying DIFFERENT NOTES are still the SAME \
work. Notes never make records different — they are merged, not chosen between.
- When genuinely unsure, answer "unsure". An unsure answer costs the historian \
one glance; a wrong "same" silently destroys a distinction.

Reply with ONLY a JSON array, one object per pair, no prose and no code fence:
[{"pair_id": "...", "verdict": "same"|"different"|"unsure", \
"confidence": 0.0-1.0, "rationale": "one sentence"}]"""


def pair_hash(row: dict) -> str:
    payload = json.dumps([row.get("a_record"), row.get("b_record")],
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def render_pair(row: dict) -> str:
    def side(tag: str, rec: dict) -> str:
        fields = [("type", rec.get("ref_type")), ("authors", rec.get("authors")),
                  ("year", rec.get("year")), ("title", rec.get("title")),
                  ("in", rec.get("container")), ("publisher", rec.get("publisher")),
                  ("edition", rec.get("edition")), ("vol", rec.get("volume")),
                  ("issue", rec.get("issue")), ("pages", rec.get("pages")),
                  ("doi", rec.get("doi")), ("isbn", rec.get("isbn"))]
        body = "\n".join(f"    {k}: {v}" for k, v in fields if v)
        return f"  {tag} [{rec.get('library')} #{rec.get('uid')}]\n{body}"
    return (f"pair_id: {row['a']}|{row['b']}\n"
            f"  score: {row['score']}  flags: {', '.join(row['blockers']) or 'none'}\n"
            f"{side('A', row['a_record'])}\n{side('B', row['b_record'])}")


def parse_verdicts(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in model reply: {text[:200]}")
    return json.loads(text[start:end + 1])


def call_claude_cli(prompt: str, model: str, timeout: int) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json"],
        input=prompt, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({proc.returncode}): {proc.stderr[:400]}")
    try:
        return json.loads(proc.stdout).get("result", proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout


def call_api(prompt: str, model: str, timeout: int) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    body = json.dumps({
        "model": model, "max_tokens": 4096, "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    return "".join(part.get("text", "") for part in payload.get("content", []))


def from_csv(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            verdict = (row.get("DECISION") or "").strip().lower()
            if not verdict:
                continue
            verdict = {"s": "same", "y": "same", "yes": "same", "same": "same",
                       "d": "different", "n": "different", "no": "different",
                       "different": "different"}.get(verdict, "unsure")
            out.append({"pair_id": row["pair_id"], "verdict": verdict,
                        "confidence": 1.0, "rationale": "human decision",
                        "source": "human"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Adjudicate ambiguous duplicate pairs.")
    ap.add_argument("--work", default="./work")
    ap.add_argument("--engine", choices=("csv", "claude", "api"), default="csv")
    ap.add_argument("--csv", help="filled review CSV (default work/review-queue.csv)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--limit", type=int, help="only adjudicate the first N pairs")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--dry-run", action="store_true", help="print the first prompt and stop")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    out_path = os.path.join(work, "decisions.jsonl")
    cache_path = os.path.join(work, "adjudication-cache.json")
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)

    existing = {d["pair_id"]: d for d in load_jsonl(out_path)} if os.path.exists(out_path) else {}

    if args.engine == "csv":
        path = args.csv or os.path.join(work, "review-queue.csv")
        decisions = from_csv(path)
        for d in decisions:
            existing[d["pair_id"]] = d
        write_jsonl(out_path, list(existing.values()))
        counts = {}
        for d in existing.values():
            counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
        print(f"{len(decisions)} human decision(s) read from {path}")
        print(f"decisions.jsonl now holds {len(existing)}: {counts}")
        return 0

    queue = load_jsonl(os.path.join(work, "review-queue.jsonl"))
    todo = []
    for row in queue:
        pid = f"{row['a']}|{row['b']}"
        h = pair_hash(row)
        if pid in existing and existing[pid].get("source") == "human":
            continue          # a human decision always wins
        if h in cache:
            existing[pid] = {**cache[h], "pair_id": pid}
            continue
        todo.append((pid, h, row))
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(queue)} in queue, {len(todo)} need a model verdict "
          f"({len(queue) - len(todo)} cached or already decided)")
    if not todo:
        write_jsonl(out_path, list(existing.values()))
        return 0

    caller = call_claude_cli if args.engine == "claude" else call_api
    for start in range(0, len(todo), args.batch_size):
        batch = todo[start:start + args.batch_size]
        body = "\n\n".join(render_pair(row) for _, _, row in batch)
        prompt = (SYSTEM + "\n\n" if args.engine == "claude" else "") + \
                 f"Decide these {len(batch)} pairs.\n\n{body}"
        if args.dry_run:
            print(prompt)
            return 0
        try:
            verdicts = parse_verdicts(caller(prompt, args.model, args.timeout))
        except Exception as exc:
            print(f"batch {start // args.batch_size} failed: {exc}", file=sys.stderr)
            continue
        by_id = {v.get("pair_id"): v for v in verdicts}
        for pid, h, _ in batch:
            v = by_id.get(pid)
            if not v:
                print(f"  no verdict returned for {pid}; left for human review",
                      file=sys.stderr)
                continue
            decision = {
                "pair_id": pid,
                "verdict": str(v.get("verdict", "unsure")).lower(),
                "confidence": float(v.get("confidence", 0.0) or 0.0),
                "rationale": v.get("rationale", ""),
                "source": f"{args.engine}:{args.model}",
                "decided": datetime.now(timezone.utc).isoformat(),
            }
            existing[pid] = decision
            cache[h] = {k: val for k, val in decision.items() if k != "pair_id"}
        done = min(start + args.batch_size, len(todo))
        print(f"  adjudicated {done}/{len(todo)}")

    write_jsonl(out_path, list(existing.values()))
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)

    counts: dict[str, int] = {}
    for d in existing.values():
        counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
    print(f"decisions.jsonl: {len(existing)} total {counts}")
    unsure = [d for d in existing.values() if d["verdict"] == "unsure"]
    if unsure:
        print(f"{len(unsure)} pair(s) still unsure — these stay unmerged and "
              f"are listed in work/still-unsure.csv")
        with open(os.path.join(work, "still-unsure.csv"), "w", encoding="utf-8-sig",
                  newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["pair_id", "rationale"])
            for d in unsure:
                writer.writerow([d["pair_id"], d.get("rationale", "")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

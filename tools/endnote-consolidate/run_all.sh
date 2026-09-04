#!/usr/bin/env bash
#
# End-to-end consolidation run.
#
#   ./run_all.sh "/path/to/EndNote libraries" ./work
#
# Stops at the review queue. Fill in the DECISION column (or run 30_adjudicate.py
# with --engine claude), then re-run with RESUME=1 to finish.
#
set -euo pipefail

ROOT="${1:?usage: run_all.sh <libraries-folder> [work-dir]}"
WORK="${2:-./work}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESUME="${RESUME:-0}"

cd "$HERE"

if [ "$RESUME" = "0" ]; then
  echo "== 00 inventory =="
  python3 00_inventory.py --root "$ROOT" --work "$WORK"

  echo "== 10 extract =="
  python3 10_extract.py --work "$WORK"

  echo "== 20 cluster =="
  python3 20_cluster.py --work "$WORK" ${CONFIG:+--config "$CONFIG"}

  QUEUE=$(python3 -c "import json;print(json.load(open('$WORK/cluster-report.json'))['review_pairs'])")
  if [ "$QUEUE" -gt 0 ]; then
    cat <<EOF

  ------------------------------------------------------------------
  $QUEUE pair(s) need a decision before merging.

    Option A (free, in a spreadsheet):
      open $WORK/review-queue.csv, fill the DECISION column with
      "same" or "different", save, then:
        RESUME=1 $0 "$ROOT" "$WORK"

    Option B (let a model take the first pass, then check its work):
      python3 30_adjudicate.py --work "$WORK" --engine claude
      RESUME=1 $0 "$ROOT" "$WORK"
  ------------------------------------------------------------------
EOF
    exit 0
  fi
fi

echo "== 30 adjudicate (reading any decisions you have made) =="
python3 30_adjudicate.py --work "$WORK" --engine csv || true

echo "== 40 merge =="
python3 40_merge.py --work "$WORK" ${PRIORITY:+--priority $PRIORITY}

echo "== 50 export =="
python3 50_export.py --work "$WORK"

echo "== 60 verify =="
python3 60_verify.py --work "$WORK"

echo
echo "Done. Import $WORK/out/consolidated.xml into a NEW empty EndNote library."

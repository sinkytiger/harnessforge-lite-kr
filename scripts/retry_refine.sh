#!/usr/bin/env bash
# Re-run a Harness^2 stream until all test tasks are recorded, waiting out network drops.
# usage: scripts/retry_refine.sh <harness_dir> <executor> <editor> <out_dir>
set -u
export PYTHONIOENCODING=utf-8
H=$1; EXEC=$2; ED=$3; OUT=$4
for attempt in $(seq 1 20); do
  python -m harnessforge refine --harness "$H" --model "$EXEC" --editor-model "$ED" --k 1 --split test --out "$OUT"
  n=$(grep -c . "$OUT/records.jsonl" 2>/dev/null || echo 0)
  echo "== attempt $attempt: $n/35 tasks recorded"
  [ "$n" -ge 35 ] && break
  sleep 120
done
echo "== done"

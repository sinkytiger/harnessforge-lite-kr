#!/usr/bin/env bash
# Full experiment queue on a free local model (Ollama). Every step resumes from cached episodes,
# so the script can be stopped and restarted. Roughly 5-6 hours on a laptop RTX 2060 with qwen3:4b.
set -u
MODEL=${MODEL:-qwen3:4b}
EDITOR=${EDITOR:-$MODEL}
SEEDS=${SEEDS:-7}
PY="python -m harnessforge"
export PYTHONIOENCODING=utf-8

echo "== E1 runtime comparison on the test split (model $MODEL, seeds $SEEDS)"
$PY run --harness direct           --model "$MODEL" --seeds $SEEDS --split test --label "Direct RAG (top-6 chunks, one call)" --out runs/e1_direct
$PY run --harness seed-notes       --model "$MODEL" --seeds $SEEDS --split test --label "Tools + free-text notes" --out runs/e1_notes
$PY run --harness seed-longharness --model "$MODEL" --seeds $SEEDS --split test --label "LongHarness seed H0" --out runs/e1_longharness

echo "== E2 Harmony search on the search split (labelled), editor $EDITOR"
$PY evolve --harness seed-longharness --model "$MODEL" --editor-model "$EDITOR" --n-sub 4 --generations 2 --out runs/e2_harmony

echo "== E3 Harness^2 test-time refinement from the Harmony pick (no answer key in the loop)"
$PY refine --harness runs/e2_harmony/best --model "$MODEL" --editor-model "$EDITOR" --k 1 --split test --out runs/e3_harness2

echo "== report"
$PY report --title "harnessforge-lite-kr results ($MODEL)" \
  --runs runs/e1_direct runs/e1_notes runs/e1_longharness \
  --records runs/e3_harness2/records.jsonl --out reports/results_raw.md

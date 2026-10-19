#!/usr/bin/env bash
# Resume every remaining step after an interruption (sleep, reboot, network loss).
# Finished episodes are cached per (harness, question, seed, model), Harmony continues from
# harmony.json, and Harness^2 skips tasks already in records.jsonl. Only the episode that was
# running at the moment of the interruption is redone.
set -u
export PYTHONIOENCODING=utf-8
PY="python -m harnessforge"
OPUS=claude-opus-5-5
HAIKU=claude-haiku-5-5

$PY check-model --model "$OPUS" || exit 1

# API-only runs (Haiku executor) go in the background; they do not use the GPU.
(
  $PY run --harness direct           --model $HAIKU --seeds 7 --split test --label "Direct RAG (Haiku 5.5)" --out runs/h1_direct
  $PY run --harness seed-notes       --model $HAIKU --seeds 7 --split test --label "Tools + free-text notes (Haiku 5.5)" --out runs/h1_notes
  $PY run --harness seed-longharness --model $HAIKU --seeds 7 --split test --label "LongHarness seed H0 (Haiku 5.5)" --out runs/h1_longharness
  $PY evolve --harness seed-longharness --model $HAIKU --editor-model $OPUS --n-sub 4 --generations 2 --out runs/h2_harmony
  bash scripts/retry_refine.sh runs/h2_harmony/best $HAIKU $OPUS runs/h3_harness2
) > runs/resume_haiku.log 2>&1 &

# GPU runs (qwen3:4b executor, Opus editor), one at a time.
$PY evolve --harness seed-longharness --model qwen3:4b --editor-model $OPUS --n-sub 4 --generations 1 --out runs/e2c_harmony_claude
bash scripts/retry_refine.sh runs/e2c_harmony_claude/best qwen3:4b $OPUS runs/e3c_harness2_claude
wait
echo "== done"

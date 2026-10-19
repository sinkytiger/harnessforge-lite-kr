#!/usr/bin/env bash
# Capable-executor condition: Claude Haiku 5.5 executes (effort low), Claude Opus 5.5 edits.
# API only, so it runs in parallel with the local-GPU queue. Every step resumes from cache.
set -u
export PYTHONIOENCODING=utf-8
PY="python -m harnessforge"
EXEC=${EXEC:-claude-haiku-5-5}
EDITOR=${EDITOR:-claude-opus-5-5}

$PY check-model --model "$EXEC" || exit 1
$PY check-model --model "$EDITOR" || exit 1

echo "== H1 runtime comparison on the test split (executor $EXEC)"
$PY run --harness direct           --model "$EXEC" --seeds 7 --split test --label "Direct RAG (Haiku 5.5)" --out runs/h1_direct
$PY run --harness seed-notes       --model "$EXEC" --seeds 7 --split test --label "Tools + free-text notes (Haiku 5.5)" --out runs/h1_notes
$PY run --harness seed-longharness --model "$EXEC" --seeds 7 --split test --label "LongHarness seed H0 (Haiku 5.5)" --out runs/h1_longharness

echo "== H2 Harmony search on the search split (executor $EXEC, editor $EDITOR)"
$PY evolve --harness seed-longharness --model "$EXEC" --editor-model "$EDITOR" --n-sub 4 --generations 2 --out runs/h2_harmony

echo "== H3 Harness^2 from the Harmony pick (executor $EXEC, editor $EDITOR)"
$PY refine --harness runs/h2_harmony/best --model "$EXEC" --editor-model "$EDITOR" --k 1 --split test --out runs/h3_harness2

echo "== done"

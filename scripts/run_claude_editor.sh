#!/usr/bin/env bash
# Strong-editor condition: Claude Opus 5.5 edits the harness, qwen3:4b (local, free) executes.
# Waits for the running qwen-editor Harmony search to finish, so the two never share the GPU.
# Then runs, in order: Harmony (Claude editor), Harness^2 from its pick (Claude editor),
# and finally Harness^2 from the qwen-editor pick (qwen editor), which the first queue skips.
set -u
export PYTHONIOENCODING=utf-8
PY="python -m harnessforge"
EDITOR=${EDITOR:-claude-opus-5-5}

echo "== waiting for the qwen-editor Harmony search to finish"
until [ -f runs/e2_harmony/best/general/system.md ]; do sleep 60; done

echo "== preflight: $EDITOR"
if ! $PY check-model --model "$EDITOR"; then
  echo "== $EDITOR is not usable (no key or rejected); running only the qwen-editor Harness^2 step"
  $PY refine --harness runs/e2_harmony/best --model qwen3:4b --k 1 --split test --out runs/e3_harness2
  exit 0
fi

echo "== E2c Harmony search, editor $EDITOR (seed evaluation reused from the qwen-editor run)"
mkdir -p runs/e2c_harmony_claude/runs
seed_hash=$(python -c "from harnessforge.harness import Harness; print(Harness.seed().hash)")
cp -n runs/e2_harmony/runs/*__${seed_hash}__s7__*.json runs/e2c_harmony_claude/runs/ 2>/dev/null || true
$PY evolve --harness seed-longharness --model qwen3:4b --editor-model "$EDITOR" --n-sub 4 --generations 2 --out runs/e2c_harmony_claude

echo "== E3c Harness^2 from the Claude-editor pick, editor $EDITOR"
$PY refine --harness runs/e2c_harmony_claude/best --model qwen3:4b --editor-model "$EDITOR" --k 1 --split test --out runs/e3c_harness2_claude

echo "== E3 Harness^2 from the qwen-editor pick, editor qwen3:4b"
$PY refine --harness runs/e2_harmony/best --model qwen3:4b --k 1 --split test --out runs/e3_harness2

echo "== done"

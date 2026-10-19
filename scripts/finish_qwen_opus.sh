#!/usr/bin/env bash
# Time-boxed finish for the qwen3:4b executor + Claude Opus 5.5 editor condition:
# one Harmony generation (4 children) instead of two, then the Harness^2 step on the test split.
set -u
export PYTHONIOENCODING=utf-8
PY="python -m harnessforge"
$PY evolve --harness seed-longharness --model qwen3:4b --editor-model claude-opus-5-5 --n-sub 4 --generations 1 --out runs/e2c_harmony_claude
$PY refine --harness runs/e2c_harmony_claude/best --model qwen3:4b --editor-model claude-opus-5-5 --k 1 --split test --out runs/e3c_harness2_claude
echo "== done"

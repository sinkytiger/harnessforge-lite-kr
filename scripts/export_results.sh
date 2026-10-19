#!/usr/bin/env bash
# Copy the small, reviewable artifacts of every experiment from runs/ (gitignored) into results/.
set -eu
rm -rf results && mkdir -p results
for pair in "qwen_executor__qwen_editor:e2_harmony" "qwen_executor__opus_editor:e2c_harmony_claude" "haiku_executor__opus_editor:h2_harmony"; do
  name=${pair%%:*}; dir=runs/${pair##*:}
  [ -f "$dir/harmony.json" ] || continue
  mkdir -p "results/harmony/$name"
  cp "$dir/harmony.json" "results/harmony/$name/"
  cp -r "$dir/best" "results/harmony/$name/picked_harness"
done
for pair in "qwen_executor__opus_editor:e3c_harness2_claude" "haiku_executor__opus_editor:h3_harness2"; do
  name=${pair%%:*}; dir=runs/${pair##*:}
  [ -f "$dir/records.jsonl" ] || continue
  mkdir -p "results/harness2/$name"
  cp "$dir/records.jsonl" "results/harness2/$name/"
  [ -d "$dir/library" ] && cp -r "$dir/library" "results/harness2/$name/library"
done
du -sh results

# X005

**Situation.** A growth-rate question needs two figures (current and prior year) from one filing. The agent read the right section but kept re-running the identical search instead of extracting both figures. It saved only one value and never computed or finalized.

**Lesson.** Block exact-repeat searches with a message telling the agent to read or extract from results it already has. Require derived answers to go through a compute step over recorded evidence. Together these push the agent to save both year values from passages already read, compute the ratio and finalize, instead of looping on search.

**Edit.** set general gate block_repeats=True; append 526 chars to general/system.md; set general gate require_compute_for_derived=True

```diff
--- a/general/gates.json
+++ b/general/gates.json
@@ -6 +6,2 @@
- "require_compute_for_derived": false
+ "require_compute_for_derived": true,
+ "block_repeats": true
--- a/general/system.md
+++ b/general/system.md
@@ -15,0 +16 @@
+Evidence discipline: right after any read that shows a needed value, upsert it (value + unit + period, citing that span) before doing anything else. Never repeat an identical search; if a search already pointed you to a document, read further offsets in it instead. For derived answers (growth %, ratio, difference), first list every input (e.g. current AND prior period from the same table) in unresolved, upsert each one, then compute from the evidence ids and finalize. Leave at least 3 turns for upsert, compute and final.
```

**Evidence.** final accepted after the edit (before: none); deficiency 13 -> 4

**Tags.** ratio_or_growth, consolidated, annual, final_figures (from task T26_rev_growth)

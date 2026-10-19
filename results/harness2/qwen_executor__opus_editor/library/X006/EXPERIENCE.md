# X006

**Situation.** The agent has already found the right annual report but cannot pin down the consolidated income-statement figure. It keeps re-issuing the same search query and paging through the document chunk by chunk, never records evidence, and runs out of turns with no answer.

**Lesson.** Block exact-repeat searches and tell the agent to target the summary financial-data section, record the figure as evidence as soon as it is read, and then convert and finalize with that evidence cited. This turns a search loop into a short read-upsert-compute-final path. Truncating to the stated decimal place (rather than rounding) should be checked separately against the answer convention.

**Edit.** set general gate block_repeats=True; append 430 chars to general/system.md; set general config history_window=5

```diff
--- a/general/config.json
+++ b/general/config.json
@@ -7 +7 @@
- "history_window": 3,
+ "history_window": 5,
--- a/general/gates.json
+++ b/general/gates.json
@@ -6 +6,2 @@
- "require_compute_for_derived": false
+ "require_compute_for_derived": false,
+ "block_repeats": true
--- a/general/system.md
+++ b/general/system.md
@@ -15,0 +16 @@
+Evidence and coverage discipline: right after every read, upsert any value that bears on the question, citing that span, before taking another action. Keep a list of the doc_id offset ranges you have already read. If the needed item is still missing, read an unread range of the same document (its start, its end, or a gap). Do not repeat a search you already ran. Once the figure is upserted, compute if needed and then finalize.
```

**Evidence.** final accepted after the edit (before: none); deficiency 10 -> 1

**Tags.** consolidated, annual, final_figures (from task T28_op_eok)

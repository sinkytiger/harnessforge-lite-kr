# X002

**Situation.** A DART filing question asks for a consolidated, cumulative-period figure from the final confirmed disclosure. A single filing contains both the parent-only (separate) statement and the consolidated statement. In the earlier run the agent read the separate statement first, recorded it, then had to re-search, re-read and re-check for corrections. It also repeated list_docs calls that brought nothing new.

**Lesson.** For consolidated cumulative-period questions, search and read the consolidated income statement section directly. Check the filing list once for any amended (정정) filing, and do not re-list or re-search after the right figure is admitted. Blocking repeated calls and folding the correction check into the first filing-list review halves the turns without changing the answer.

**Edit.** set general gate block_repeats=True; append 458 chars to general/system.md; append 575 chars to domain/dart/domain.md; set domain gate correction_check=True

```diff
--- a/domain/dart/domain.md
+++ b/domain/dart/domain.md
@@ -2,0 +3 @@
+Final-filing rule: call list_docs ONCE. From it, pick the filings for the asked 사업연도 and period. The final confirmed source is the latest-submitted one: [기재정정] or [정정] beats the original, and 잠정 (preliminary) disclosures never count. If a correction exists for that period, read it. If the list shows none, the original is final, so do not re-list or re-search. Basis rule: before upserting, confirm the statement title says 연결 (not 별도) when the question asks 연결. Take the cumulative column (누적, e.g. 1~6월), not the 3-month column. Name the basis and period in the statement.
--- a/domain/dart/gates.json
+++ b/domain/dart/gates.json
@@ -2 +2 @@
- "correction_check": false,
+ "correction_check": true,
--- a/general/gates.json
+++ b/general/gates.json
@@ -6 +6,2 @@
- "require_compute_for_derived": false
+ "require_compute_for_derived": false,
+ "block_repeats": true
--- a/general/system.md
+++ b/general/system.md
@@ -15,0 +16 @@
+Discipline: never repeat an action whose result you already have (same list_docs, same search); reuse the earlier result from your notes. Before upserting a number, check that the table's heading matches EVERY qualifier in the question (entity, basis such as consolidated/separate, period, cumulative vs. quarter, unit). If any qualifier does not match, do not upsert; find the right table. When an unresolved item is settled or no longer matters, remove it.
```

**Evidence.** same answer with 49499 -> 28325 tokens

**Tags.** cumulative, consolidated, final_figures (from task T18_h1_rev_eok)

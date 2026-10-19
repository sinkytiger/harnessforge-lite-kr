# X002

**Situation.** Korean DART filing asks for a quarter-only (3-month) consolidated operating profit in 억원 from a half-year or quarterly report. The income statement gives both 3-month and cumulative columns in 천원, and the figure is a loss shown with parentheses or a minus sign. Before the edit, the agent stored the value without its sign or label, then looped on the same compute and never submitted a final answer.

**Lesson.** When pulling a figure from a DART income statement, record the line label, the period column (3-month vs cumulative) and the sign (parentheses or 손실 mean negative) in the upserted evidence. Convert 천원 to 억원 by dividing by 100,000, round as asked, and submit the final answer as soon as the compute succeeds instead of recomputing the same expression.

**Edit.** append 492 chars to domain/dart/domain.md; append 321 chars to domain/dart/tool_guidance.md

```diff
--- a/domain/dart/domain.md
+++ b/domain/dart/domain.md
@@ -1,0 +2 @@
+Period columns: 반기보고서/분기보고서 income statements show both a 3-month column (3개월) and a cumulative column (누적). For a single-quarter question (e.g. 2분기 4~6월), copy the 3-month column of the 당기 period, not 누적 and not 전기. Final basis: if list_docs shows a [정정] filing or a later filing for the same period, use it instead of the original or a preliminary (잠정) figure. Check the unit line of the same table before converting (천원 → 억원 divide by 100,000; 백만원 → 억원 divide by 100), then round as asked.
--- a/domain/dart/tool_guidance.md
+++ b/domain/dart/tool_guidance.md
@@ -0,0 +1 @@
+Order for DART figure questions: list_docs, check for [정정], read the table, confirm the period column and unit, upsert the value with unit, compute the conversion once, then finalize immediately with the rounded result citing that evidence. Never repeat an identical compute; a repeated result means it is time to answer.
```

**Evidence.** final accepted after the edit (before: none); deficiency 5 -> 0

**Tags.** quarter_3m, consolidated, final_figures (from task T08_q2_op_eok)

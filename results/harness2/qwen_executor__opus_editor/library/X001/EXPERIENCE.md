# X001

**Situation.** A Korean DART filing question asks for a consolidated figure (net income, revenue, operating profit) converted to 억원 from a filing that reports in 백만원. The agent finds and reads the correct annual report and computes the conversion. It then loops on repeated identical computes, re-reads and re-searches because it never records the value as evidence, and it never finalizes.

**Lesson.** Give the agent a domain recipe for DART figure questions: list filings to pick the final annual report, read it, upsert the consolidated figure with its unit as cited evidence, compute the unit conversion from that evidence ref, then finalize. Without an admitted evidence entry, the agent keeps recomputing and re-reading instead of answering.

**Edit.** write skill domain/dart_figure_recipe (when: 매출액, 영업이익, 순이익, 비중, 억원, 연결); set domain gate correction_check=True

```diff
--- a/domain/dart/gates.json
+++ b/domain/dart/gates.json
@@ -2 +2 @@
- "correction_check": false,
+ "correction_check": true,
--- a/domain/dart/skills/dart_figure_recipe.md
+++ b/domain/dart/skills/dart_figure_recipe.md
@@ -6,6 +6 @@
-1. Call list_docs for the company. Pick the latest 사업보고서 for the asked year. If a [기재정정] version exists, use it, because it is the final figure.
-2. Search that filing using a section title, not the question text: '요약재무정보', '연결 포괄손익계산서', or '매출실적' / '부문별 매출' for segment shares. Never repeat a query. If the results do not change, read the top hit's doc_id and offset.
-3. Read the hit. Find the column for the asked year and the table's (단위: ...) line.
-4. Upsert the raw cell immediately. Include its unit and keep △ as a minus sign.
-5. Use compute for every conversion: 억원 = 백만원/100 = 천원/100000. Share % = segment / total * 100. Round as the question asks.
-6. Answer with the computed number only.
+1. list_docs for the company. If a [정정] or later-dated report for the same period exists, use the latest one. Do not use 잠정 or 예비 figures. 2. Read the 연결 손익계산서 (consolidated income statement), not the 별도 (standalone) one. Use the 당기 column for the asked fiscal year. 3. Copy the unit line (단위: 원/천원/백만원) that sits above the table. 4. Convert exactly once: 백만원÷100, 천원÷100000, 원÷100000000. Treat △ as minus. Round as asked. 5. Right after the compute, upsert one statement with the converted value, citing the S# span that shows both the figure and the unit. Then give the final answer. Never repeat the same compute.
```

**Evidence.** final accepted after the edit (before: none); deficiency 6 -> 0

**Tags.** consolidated, annual, final_figures (from task T01_net_eok)

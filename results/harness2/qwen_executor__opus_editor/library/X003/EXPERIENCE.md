# X003

**Situation.** A Korean DART financial-figure question asks for the 'final confirmed' (최종 확정) consolidated amount in a stated unit. Several filings exist for the same fiscal year, including a correction ([기재정정]). Without guidance, the agent reads the original report once and then repeats identical searches for the corrected filing, never reading or recording anything.

**Lesson.** For DART figure questions, list the company's filings first, pick the latest correction for the target period, read the relevant section, and upsert the figure with its unit before converting units with compute. A final answer can only cite evidence ids that were already admitted, so record the figure before trying to finalize rather than retrying compute or final with an id that does not exist yet.

**Edit.** append 459 chars to domain/dart/tool_guidance.md; write skill domain/dart_figure_recipe (when: 매출액, 영업이익, 순이익, 비중, 억원, 연결)

```diff
--- a/domain/dart/skills/dart_figure_recipe.md
+++ b/domain/dart/skills/dart_figure_recipe.md
@@ -6,6 +6 @@
-1. Call list_docs for the company. Pick the latest 사업보고서 for the asked year. If a [기재정정] version exists, use it, because it is the final figure.
-2. Search that filing using a section title, not the question text: '요약재무정보', '연결 포괄손익계산서', or '매출실적' / '부문별 매출' for segment shares. Never repeat a query. If the results do not change, read the top hit's doc_id and offset.
-3. Read the hit. Find the column for the asked year and the table's (단위: ...) line.
-4. Upsert the raw cell immediately. Include its unit and keep △ as a minus sign.
-5. Use compute for every conversion: 억원 = 백만원/100 = 천원/100000. Share % = segment / total * 100. Round as the question asks.
-6. Answer with the computed number only.
+1. list_docs for the company. Pick the 사업보고서 for the asked fiscal year. If a [기재정정]/[정정] version of it exists, use the latest-dated one; otherwise the original is final. 2. search the line item with the company filter, then read the hit offset inside that doc. If there is no hit, read onward from the cover in steps until you reach the 연결 손익계산서. 3. upsert the figure with its label, the 당기 column, the sign (△ or () means negative), the unit line (단위) and the span ref. 4. compute the 억원 conversion from that ref (백만원/100, 천원/100000, 원/1e8) and round as asked. 5. finalize right after the compute succeeds.
--- a/domain/dart/tool_guidance.md
+++ b/domain/dart/tool_guidance.md
@@ -0,0 +1 @@
+DART navigation: to check for [기재정정]/[정정] versions or later filings, call list_docs once for the company. Do not search filing titles, because search matches body text, not titles. When you search a line item (영업이익, 매출액), filter by company and immediately read the returned doc_id+offset that belongs to the chosen filing. Never send the same search twice. If a search fails, read further into the chosen filing (offset +1400) to reach the 연결 손익계산서 or 요약재무정보.
```

**Evidence.** final accepted after the edit (before: none); deficiency 16 -> 4

**Tags.** consolidated, annual, final_figures (from task T14_op_eok)

# X004

**Situation.** A DART-style filing question asks for one consolidated figure, such as net income, in a target unit like 억원 at a stated precision. The filing reports the figure in a different unit (e.g. 백만원). Without a recipe, the agent re-searched and re-read the same document. It then called compute on an evidence id it had never created, and it ran out of turns without a final answer.

**Lesson.** Once the consolidated statement row is found, first upsert the exact reported value and its unit as evidence, citing the read span. Then compute the unit conversion (백만원→억원 = ÷100) from that evidence id, and finalize with the requested precision. Never reference an evidence id in compute before upsert has admitted it, and stop searching once the figure has been read.

**Edit.** write skill domain/dart_figure_recipe (when: 매출액, 영업이익, 순이익, 비중, 억원, 연결); append 233 chars to domain/dart/domain.md

```diff
--- a/domain/dart/domain.md
+++ b/domain/dart/domain.md
@@ -1,0 +2 @@
+Consolidated net income (연결 당기순이익) is the total 당기순이익 line of the 연결 포괄손익계산서 (or 연결손익계산서), not the line attributable to 지배기업 소유주. 사업보고서 also repeats it in 요약재무정보. Either source is acceptable if it is marked 연결 and its unit is stated.
--- a/domain/dart/skills/dart_figure_recipe.md
+++ b/domain/dart/skills/dart_figure_recipe.md
@@ -6,6 +6,5 @@
-1. Call list_docs for the company. Pick the latest 사업보고서 for the asked year. If a [기재정정] version exists, use it, because it is the final figure.
-2. Search that filing using a section title, not the question text: '요약재무정보', '연결 포괄손익계산서', or '매출실적' / '부문별 매출' for segment shares. Never repeat a query. If the results do not change, read the top hit's doc_id and offset.
-3. Read the hit. Find the column for the asked year and the table's (단위: ...) line.
-4. Upsert the raw cell immediately. Include its unit and keep △ as a minus sign.
-5. Use compute for every conversion: 억원 = 백만원/100 = 천원/100000. Share % = segment / total * 100. Round as the question asks.
-6. Answer with the computed number only.
+1. Call list_docs once for the company. Pick the latest filing for the target period, preferring [기재정정]/[정정] over the original report. Never search filing titles.
+2. search the line item (e.g. 당기순이익) with the company filter, then read that doc at the returned offset.
+3. As soon as a read span shows the line in the 연결 statement, upsert it immediately. Include the line label, the 당기 column, the unit line (단위: 백만원/천원/원) and the sign (△ or parentheses mean negative), with refs [S#]. Do not re-read the same range.
+4. compute the conversion using ONLY the E# id that upsert returned (백만원/100, 천원/100000, 원/100000000). Round as asked.
+5. Submit final right after the compute succeeds, citing that E#.
```

**Evidence.** final accepted after the edit (before: none); deficiency 12 -> 0

**Tags.** consolidated, annual, final_figures (from task T25_net_eok)

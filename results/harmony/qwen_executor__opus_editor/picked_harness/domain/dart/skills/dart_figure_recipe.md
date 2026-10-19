---
name: dart_figure_recipe
when: 매출액, 영업이익, 순이익, 비중, 억원, 연결
summary: Fixed recipe to locate, extract and convert a consolidated figure from the latest final DART filing
---
1. Call list_docs for the company. Pick the latest 사업보고서 for the asked year. If a [기재정정] version exists, use it, because it is the final figure.
2. Search that filing using a section title, not the question text: '요약재무정보', '연결 포괄손익계산서', or '매출실적' / '부문별 매출' for segment shares. Never repeat a query. If the results do not change, read the top hit's doc_id and offset.
3. Read the hit. Find the column for the asked year and the table's (단위: ...) line.
4. Upsert the raw cell immediately. Include its unit and keep △ as a minus sign.
5. Use compute for every conversion: 억원 = 백만원/100 = 천원/100000. Share % = segment / total * 100. Round as the question asks.
6. Answer with the computed number only.

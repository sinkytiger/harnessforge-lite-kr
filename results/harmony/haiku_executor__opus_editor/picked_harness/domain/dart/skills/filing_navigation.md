---
name: filing_navigation
when: *
summary: Find the right filing and table fast: list_docs, then exact line-item search with company filter, then read at offset
---
1. Call list_docs for the company first. Pick the filing whose period matches the question: 사업보고서 for annual or fiscal-year figures, 반기보고서 for half-year figures, 분기보고서 for quarter figures. If there are several, take the latest filing that covers that period.
2. Search with the exact Korean line-item name (e.g. 매출액, 영업이익, 당기순이익, 자산총계) plus the company filter. Add 연결 or 별도 if the question specifies it. Prefer hits in the 재무제표 section over 주석 or 요약 sections.
3. Read at the returned doc_id and offset. Check the (단위: …) line and the period column header before copying the value.
4. Do not search broadly or read several documents when a matching filing exists. Upsert as soon as the value is found.

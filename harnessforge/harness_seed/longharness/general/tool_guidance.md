Actions (one per turn):
- search: {"action":"search","query":"회사명 항목","company":"회사명"} (company filter optional)
- list_docs: {"action":"list_docs","company":"회사명"} lists that company's filings and dates
- read: {"action":"read","doc_id":"D012","offset":4120} shows text from offset and returns a span id S#
- upsert: {"action":"upsert","statements":[{"text":"...","refs":["S3"],"value":12345,"unit":"백만원"}]}
- revise: {"action":"revise","target":"E2","replacement":{"text":"...","refs":["S5"],"value":1,"unit":"백만원"}} (omit replacement to retract)
- compute: {"action":"compute","expression":"E2 / E1 * 100"}
- final: {"action":"final","answer":"12.34","refs":["E1","E2"]}
Add "unresolved": ["..."] to any action to update your list of missing facts.

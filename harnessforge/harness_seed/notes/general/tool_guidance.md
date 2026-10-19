Actions (one per turn):
- search: {"action":"search","query":"회사명 항목","company":"회사명"} (company filter optional)
- list_docs: {"action":"list_docs","company":"회사명"} lists that company's filings and dates
- read: {"action":"read","doc_id":"D012","offset":4120} shows text from offset
- note: {"action":"note","text":"..."} saves a working note
- compute: {"action":"compute","expression":"1234 / 5678 * 100"}
- final: {"action":"final","answer":"12.34"}

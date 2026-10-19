# X004

**Situation.** A DART financial-figure question asking for the final confirmed filing value, where the company's filing list includes an amended ([기재정정]) annual report alongside the original, and the agent must pick the authoritative document and locate the consolidated net income line.

**Lesson.** Domain guidance that tells the agent to go straight to the latest amended report for 'final confirmed' questions, plus a correction check gate, lets it read the summary consolidated financials in one targeted read instead of paging sequentially. It gets the same correct answer in fewer turns and tokens. Keep the gate, but judge it on efficiency, since correctness was already achieved without it.

**Edit.** append 487 chars to domain/dart/domain.md; set domain gate correction_check=True

```diff
--- a/domain/dart/domain.md
+++ b/domain/dart/domain.md
@@ -2,0 +3 @@
+Final-filing rule: use ONE list_docs call. Among filings for the asked 사업연도/period, the latest-submitted wins ([기재정정]/[정정] beats the original; 잠정 never counts). Once a value is admitted from that filing, the correction check is satisfied: mark it resolved and finalize. Do not re-list or re-search. Statement basis: for 연결 당기순이익, take the total 당기순이익(손실) line of the consolidated statement (연결손익계산서 or 요약연결재무정보 of the same final filing), not the 지배기업 소유주지분 line and not the 별도 statement.
--- a/domain/dart/gates.json
+++ b/domain/dart/gates.json
@@ -2 +2 @@
- "correction_check": false,
+ "correction_check": true,
```

**Evidence.** same answer with 34303 -> 22660 tokens

**Tags.** consolidated, annual, final_figures (from task T34_net_eok)

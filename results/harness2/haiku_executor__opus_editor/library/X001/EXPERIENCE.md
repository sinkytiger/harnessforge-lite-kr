# X001

**Situation.** A DART financial-figure question asks for the final confirmed value. The agent has already read and cited a figure from the most recent correction filing (기재정정 사업보고서) that it found in the filing list. Without guidance it keeps running redundant list_docs and searches to re-confirm that no later correction exists, even though the filing list already showed which correction filing is latest.

**Lesson.** When the latest correction filing in the list has been read and the value comes from it, treat the correction check as satisfied and finalize instead of re-listing or re-searching. A domain note plus a correction_check gate that states this condition explicitly cut the turns roughly in half with the same answer.

**Edit.** append 429 chars to domain/dart/domain.md; set domain gate correction_check=True

```diff
--- a/domain/dart/domain.md
+++ b/domain/dart/domain.md
@@ -2,0 +3 @@
+Final-filing rule: from ONE list_docs call, take the filings for the asked 사업연도 and period. The final confirmed source is the latest-submitted one ([기재정정] or [정정] beats the original; 잠정/preliminary disclosures never count). If a correction filing shows 정정 전/정정 후, use 정정 후. Once you have read a value from the latest-dated filing, do not re-run list_docs or search for further corrections; compute the unit conversion and answer.
--- a/domain/dart/gates.json
+++ b/domain/dart/gates.json
@@ -2 +2 @@
- "correction_check": false,
+ "correction_check": true,
```

**Evidence.** same answer with 39169 -> 21497 tokens

**Tags.** consolidated, annual, final_figures (from task T13_net_eok)

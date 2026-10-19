# X003

**Situation.** Year-over-year growth questions on DART filings where both the current and prior-year figures are needed. The agent would otherwise read two separate annual reports, one per year. The latest annual report's comparative statement already shows the prior period (전기) alongside the current period (당기).

**Lesson.** When computing YoY change from a final annual filing, take both the current-period and prior-period values from the same latest report's comparative financial statement. That way the prior figure reflects any restatement, and it saves extra searches and reads. Keep the guidance in the domain notes and make the correction check a gate, so the agent uses the most recent filing's comparatives rather than the original prior-year report.

**Edit.** append 490 chars to domain/dart/domain.md; set domain gate correction_check=True

```diff
--- a/domain/dart/domain.md
+++ b/domain/dart/domain.md
@@ -2,0 +3 @@
+Growth-rate rule: for YoY change, take BOTH years from the same final filing for the asked year: the current column (당기, 제N기) and the prior column (전기, 제N-1기) of one statement. The prior column reflects restatements, so do not pull the prior year from the older report. Final-filing rule: from ONE list_docs call, pick the latest-submitted report for the asked 사업연도. [기재정정]/[정정] beats the original, and 잠정 disclosures never count. State in a note which filing is final, then do not re-list.
--- a/domain/dart/gates.json
+++ b/domain/dart/gates.json
@@ -2 +2 @@
- "correction_check": false,
+ "correction_check": true,
```

**Evidence.** same answer with 45026 -> 26681 tokens

**Tags.** ratio_or_growth, consolidated, annual, final_figures (from task T26_rev_growth)

# Benchmark v2 and the real-filing set

v1 has 51 questions, one search split and one test split, and every question can be answered. That was
enough to compare harnesses with a capable executor, but too small and too regular to say more. v2 widens
the question set in four ways, adds a third split, and adds a small set of real DART filings.
**No model has been run on v2 or the real set yet**; every result in the README is from v1.

| | v1 | v2 (synthetic) | real (DART) |
|---|---|---|---|
| Companies | 16 fictional | 30 fictional | 6 listed companies |
| Filings | 93 | 234 | 6 FY2025 사업보고서 |
| Characters | 597k | 1.26M | 4.93M |
| Questions | 51 | 173 | 20 |
| Splits | search 16 / test 35 | search 46 / validation 35 / test 92 | real 20 |
| Unanswerable | none | 15 | 2 |
| Corpus sha (first 16) | `908aba588c8cc5cc` | `2fb66f1bd2fb5823` | depends on DART data |

```bash
python -m harnessforge validate --bench v2
```

```bash
python -m harnessforge build --bench v2 --out data/corpus_v2
```

v1 stays the default (`--bench v1`), and its corpus is unchanged byte for byte, so the published v1 numbers
can still be reproduced.

## What is new in v2

**Three splits, by company.** *search* (8 companies) is the only split an editor may see gold answers for
(Harmony refuses any other split). *validation* (6 companies) is for choosing rules, such as when Harness²
is worth its cost, without touching the test split. *test* (16 companies) is for reporting only. No company
appears in two splits, and question ids start with S, V or T.

**Filing types.** On top of v1's annual, `[기재정정]` annual, Q1, half-year and preliminary filings:

* Q3 reports (분기보고서 2025.09), with separate 3-month and 9-month cumulative columns
* audit reports (감사보고서) that repeat the statements in a different layout
* corrections of a preliminary disclosure (`[기재정정]` 잠정실적 공정공시)
* a change-of-name notice (주요사항보고서(상호변경)); filings before the change use the old name
* restated prior-year figures (재작성) in the FY2025 annual report
* some annual reports printed in 천원 rather than 백만원

**Question types.** 21 kinds, up from 11; three of them are unanswerable kinds (below). The seven new
answerable kinds are 2-year revenue CAGR, Q3 3-month revenue,
Q4 operating profit derived as the annual figure minus the Q3 cumulative figure, ROE on average equity,
the change in dividend per share in 원, a dividend that appears only under the company's old name, and
picking the company with the *second*-highest margin among four. The calculator now allows a constant
power, so CAGR can be computed with the same tool (`** 0.5`); exponents are bounded and may not use names.

**Traps.** Besides v1's traps, v2 records the figure before restatement, a preliminary figure that a later
correction replaced, the one-year growth or the un-annualised two-year growth instead of the CAGR, the
annual or Q3 figure instead of the derived Q4, year-end equity instead of average equity, the first-ranked
company instead of the second, and the dividend level instead of its change. Each trap is stored as the
exact wrong answer it produces, so a report can say which mistake a wrong answer was.

**Unanswerable questions.** Every v2 question ends with the same clause, "공시에서 확인할 수 없으면 '알 수
없음'이라고 답하시오", so the wording never gives away whether it can be answered. Fifteen cannot: a
period not yet reported, an item no filing discloses, and a company that is not in the corpus. Scoring:

* an unanswerable question is correct only when the answer abstains; a number counts as
  `answered_unanswerable`
* an answerable question answered with an abstention is wrong, with status `abstained`
* an abstaining final answer needs no evidence ids, but only when the question carries the clause, so v1
  behaviour is unchanged

The oracle policy solves all 173 questions within the turn budget, with the seed gates and with every gate
on. CI checks this.

## The real-filing set

```bash
python -m harnessforge build-real --out data/dart_real
```

```bash
python -m harnessforge validate --bench real
```

It needs your own free DART OpenAPI key in the `DART_API_KEY` environment variable. The key is read from
the environment only and is never printed or saved. Raw filings and the converted text are written under
`data/dart_real/` (ignored by git); the repository ships the code, not the filings.

* **Documents:** the latest FY2025 사업보고서 of 삼성전자, 현대자동차, NAVER, 카카오, LG전자 and
  POSCO홀딩스. LG전자's is a `[기재정정]` filing. DART XML is converted to plain text, one line per
  paragraph and one ` | ` line per table row, with empty cells kept so columns stay aligned.
* **Gold answers:** the consolidated full statements API (`fnlttSinglAcntAll`, CFS). A figure is used only
  if it is found printed in the filing under a table header of the matching unit (`단위 : 백만원`, `천원` or
  `원`), and the gold is computed from the printed figure. All 72 figures that were looked up were found.
* **Questions:** 18 answerable ones (three per company, rotating among revenue in 억원, operating margin,
  debt ratio and revenue growth) and 2 unanswerable ones (a quarter not yet reported and a company that is
  not in the set). The oracle solves all 20 with every gate on.

The real set is a sanity check that the harnesses work on real filings, not a benchmark: 20 questions on
six large companies is too few for comparisons. Because DART can add corrections, the set records each
filing's receipt number and a text hash in `meta.json`.

## Before running models on v2

* Pilot first: a few questions per split, to check token use per episode on the longer filings.
* Decide the comparison before looking at test results, on the validation split.
* The real filings are about 820k characters each, much longer than the synthetic ones, so read
  windows and search depth matter more there.

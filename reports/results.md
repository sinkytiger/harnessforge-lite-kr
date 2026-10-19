# Results

Test split: 35 questions about 11 companies that the search never saw. One sampling seed (7). The qwen3:4b executor runs locally through Ollama on a laptop RTX 2060 (6 GB). Claude models run through the Anthropic API (executor effort low, editor effort medium). Dollar figures are API list prices; local runs cost $0.

## Executor: qwen3:4b (local GPU)

| System | Correct | Accepted final | Turns | Tokens / question | $ / question |
|---|---|---|---|---|---|
| Direct RAG | 2/35 (5.7%) | no gates | 1.0 | 3,590 | 0.0000 |
| Tools + notes | 1/35 (2.9%) | 34% | 13.3 | 26,074 | 0.0000 |
| LongHarness seed H0 | 0/35 (0.0%) | 26% | 14.1 | 31,102 | 0.0000 |
| Harmony pick H†, Opus editor | 1/35 (2.9%) | 29% | 13.9 | 34,515 | 0.0000 |
| H† + Harness² step, Opus editor | 5/35 (14.3%) | 43% | 12.5 | 122,877 | 0.1075 |

### Harmony search, qwen3:4b editor (search split, 16 questions)

| Harness | Gen | λ (acc, eff) | Edit | Search-split accuracy | Tokens / question | Pareto front |
|---|---|---|---|---|---|---|
| `e55373a1f210` **H†** | 0 | seed | – | 0.0% | 31,407 |  |
| `e42e442da23f` | 1 | (0.20, 0.80) | logic/general: append 136 chars to general/system.md | 0.0% | 30,705 |  |
| `e86ba6c29ae1` | 1 | (0.40, 0.60) | logic/general: append 163 chars to general/system.md | 0.0% | 33,848 |  |
| `cc173f362748` | 1 | (0.60, 0.40) | generalize/general: move skill table_reading: general -> domain | 0.0% | 34,008 |  |
| `1e80b2536251` | 1 | (0.80, 0.20) | logic/general: set general gate block_repeats=True | 0.0% | 29,661 | yes |
| `c9141bd94748` | 2 | (0.80, 0.20) | logic/general: set general gate block_repeats=False | 0.0% | 33,053 |  |

Editor `qwen3:4b`: 20 calls. Edits rejected before evaluation: 3 of 8 (component 'logic' cannot set search_k; the operations did not change the harness; write_skill needs name and content).

### Harmony search, Claude Opus 5.5 editor (search split, 16 questions)

| Harness | Gen | λ (acc, eff) | Edit | Search-split accuracy | Tokens / question | Pareto front |
|---|---|---|---|---|---|---|
| `e55373a1f210` | 0 | seed | – | 0.0% | 31,407 |  |
| `ca8b4cfc7542` | 1 | (0.20, 0.80) | logic/general: set general gate block_repeats=True; append 525 chars to general/system.md | 6.2% | 29,356 | yes |
| `fbfb18783fb9` | 1 | (0.40, 0.60) | tools/general: replace text in general/tool_guidance.md; set general config snippet_chars=240 | 0.0% | 32,342 |  |
| `82dc11db099d` **H†** | 1 | (0.60, 0.40) | skills/domain: write skill domain/dart_figure_recipe (when: 매출액, 영업이익, 순이익, 비중, 억원, 연결) | 12.5% | 34,373 | yes |
| `e59796b63bba` | 1 | (0.80, 0.20) | skills/general: write skill general/evidence_ledger (when: *) | 6.2% | 36,047 |  |

Editor `anthropic:claude-opus-5-5`: 8 calls, $0.24. Edits rejected before evaluation: 0 of 4.

### Harness² test-time step, Claude Opus 5.5 editor (no answer key in the loop)

* Compose decisions: keep 27, adopt_domain 4, adopt_invariant 3, merge 1.
* Valid proposals: invariant 35/35, domain 34/35.
* The deliverable differs from the reference answer on 7 of 35 tasks: newly correct 4 (T01_net_eok, T14_op_eok, T25_net_eok, T26_rev_growth), newly wrong 0 (none).
* Library entries written: 6. Editor cost $3.76.

## Executor: Claude Haiku 5.5 (API)

| System | Correct | Accepted final | Turns | Tokens / question | $ / question |
|---|---|---|---|---|---|
| Direct RAG | 11/35 (31.4%) | no gates | 1.0 | 4,821 | 0.0007 |
| Tools + notes | 26/35 (74.3%) | 100% | 8.5 | 23,513 | 0.0032 |
| LongHarness seed H0 | 29/35 (82.9%) | 100% | 8.2 | 29,007 | 0.0039 |
| LongHarness seed H0, second run | 31/35 (88.6%) | 100% | 8.7 | 31,217 | 0.0042 |
| Harmony pick H†, Opus editor | 29/35 (82.9%) | 97% | 8.4 | 32,232 | 0.0042 |
| Harmony pick H†, second run without edits (control) | 29/35 (82.9%) | 100% | 8.4 | 32,110 | 0.0042 |
| H† + Harness² step, Opus editor | 34/35 (97.1%) | 97% | 8.1 | 117,603 | 0.1064 |

### Harmony search, Claude Opus 5.5 editor (search split, 16 questions)

| Harness | Gen | λ (acc, eff) | Edit | Search-split accuracy | Tokens / question | Pareto front |
|---|---|---|---|---|---|---|
| `e55373a1f210` | 0 | seed | – | 93.8% | 29,605 |  |
| `0f283002b46a` | 1 | (0.20, 0.80) | skills/domain: write skill domain/eok_unit_conversion (when: 억원, 단위) | 100.0% | 35,292 |  |
| `9c95b736436d` | 1 | (0.40, 0.60) | logic/general: set general gate require_compute_for_derived=True; append 355 chars to general/system.md | 100.0% | 30,970 |  |
| `2a2eb32810e4` | 1 | (0.60, 0.40) | logic/domain: set domain gate unit_declared=True; append 296 chars to domain/dart/domain.md | 100.0% | 30,853 |  |
| `0773fe9306e6` | 1 | (0.80, 0.20) | tools/general: set general config snippet_chars=240; set general config search_k=3; append 379 chars to genera | 87.5% | 31,491 |  |
| `341b7f8eb595` | 2 | (0.20, 0.80) | skills/domain: write skill domain/eok_unit_conversion (when: 억원, 단위) | 100.0% | 34,365 |  |
| `4b7dc00e1f2b` | 2 | (0.40, 0.60) | logic/general: set general config history_window=2; set general config thought_chars=160; append 168 chars to  | 100.0% | 32,581 |  |
| `ec2b19f64615` | 2 | (0.60, 0.40) | tools/general: set general config read_chars=900; set general config snippet_chars=240; append 205 chars to ge | 87.5% | 29,873 |  |
| `e1e22addc1a0` **H†** | 2 | (0.80, 0.20) | skills/domain: write skill domain/filing_navigation (when: *) | 100.0% | 27,226 | yes |

Editor `anthropic:claude-opus-5-5`: 19 calls, $0.39. Edits rejected before evaluation: 0 of 8.

### Harness² test-time step, Claude Opus 5.5 editor (no answer key in the loop)

* Compose decisions: keep 19, adopt_domain 11, adopt_invariant 3, merge 2.
* Valid proposals: invariant 35/35, domain 35/35.
* The deliverable differs from the reference answer on 6 of 35 tasks: newly correct 5 (T08_q2_op_eok, T20_rev_growth, T24_h1_rev_eok, T27_debt_ratio, T28_op_eok), newly wrong 0 (none).
* Library entries written: 4. Editor cost $3.26.

## Where the wrong answers went (all systems)

| System | Wrong or missing | No answer | before_correction | consolidated_basis | preliminary | separate_basis | unit_slip | Other wrong |
|---|---|---|---|---|---|---|---|---|
| qwen3:4b · Direct RAG | 33 | 1 | 2 | 1 | 3 | 0 | 9 | 17 |
| qwen3:4b · Tools + notes | 34 | 23 | 0 | 0 | 0 | 3 | 3 | 5 |
| qwen3:4b · LongHarness seed H0 | 35 | 26 | 1 | 0 | 1 | 2 | 1 | 4 |
| qwen3:4b · Harmony pick H†, Opus editor | 34 | 25 | 0 | 0 | 0 | 1 | 2 | 6 |
| qwen3:4b · H† + Harness² step, Opus editor | 30 | 20 | 0 | 0 | 0 | 2 | 2 | 6 |
| Claude Haiku 5.5 · Direct RAG | 24 | 0 | 0 | 0 | 5 | 0 | 8 | 11 |
| Claude Haiku 5.5 · Tools + notes | 9 | 0 | 0 | 0 | 0 | 1 | 6 | 2 |
| Claude Haiku 5.5 · LongHarness seed H0 | 6 | 0 | 0 | 0 | 0 | 0 | 4 | 2 |
| Claude Haiku 5.5 · LongHarness seed H0, second run | 4 | 0 | 0 | 0 | 0 | 0 | 2 | 2 |
| Claude Haiku 5.5 · Harmony pick H†, Opus editor | 6 | 1 | 0 | 0 | 0 | 2 | 1 | 2 |
| Claude Haiku 5.5 · Harmony pick H†, second run without edits (control) | 6 | 0 | 1 | 0 | 0 | 1 | 1 | 3 |
| Claude Haiku 5.5 · H† + Harness² step, Opus editor | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |

## Correct answers by question type

| System | compare_margin | debt_ratio | h1_rev_eok | net_eok | op_eok | op_margin | q2_op_eok | rev_eok | rev_growth | seg_share | sep_rev_eok |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3:4b · Direct RAG | 0/2 | 0/2 | 0/5 | 0/5 | 1/2 | 0/3 | 0/4 | 0/2 | 1/6 | 0/2 | 0/2 |
| qwen3:4b · Tools + notes | 0/2 | 0/2 | 1/5 | 0/5 | 0/2 | 0/3 | 0/4 | 0/2 | 0/6 | 0/2 | 0/2 |
| qwen3:4b · LongHarness seed H0 | 0/2 | 0/2 | 0/5 | 0/5 | 0/2 | 0/3 | 0/4 | 0/2 | 0/6 | 0/2 | 0/2 |
| qwen3:4b · Harmony pick H†, Opus editor | 0/2 | 0/2 | 0/5 | 1/5 | 0/2 | 0/3 | 0/4 | 0/2 | 0/6 | 0/2 | 0/2 |
| qwen3:4b · H† + Harness² step, Opus editor | 0/2 | 0/2 | 0/5 | 3/5 | 1/2 | 0/3 | 0/4 | 0/2 | 1/6 | 0/2 | 0/2 |
| Claude Haiku 5.5 · Direct RAG | 1/2 | 1/2 | 1/5 | 2/5 | 0/2 | 2/3 | 1/4 | 0/2 | 1/6 | 1/2 | 1/2 |
| Claude Haiku 5.5 · Tools + notes | 2/2 | 1/2 | 3/5 | 3/5 | 1/2 | 3/3 | 2/4 | 2/2 | 6/6 | 2/2 | 1/2 |
| Claude Haiku 5.5 · LongHarness seed H0 | 2/2 | 1/2 | 3/5 | 5/5 | 0/2 | 3/3 | 3/4 | 2/2 | 6/6 | 2/2 | 2/2 |
| Claude Haiku 5.5 · LongHarness seed H0, second run | 2/2 | 1/2 | 5/5 | 4/5 | 1/2 | 3/3 | 3/4 | 2/2 | 6/6 | 2/2 | 2/2 |
| Claude Haiku 5.5 · Harmony pick H†, Opus editor | 2/2 | 1/2 | 4/5 | 5/5 | 1/2 | 3/3 | 3/4 | 2/2 | 5/6 | 1/2 | 2/2 |
| Claude Haiku 5.5 · Harmony pick H†, second run without edits (control) | 2/2 | 1/2 | 5/5 | 5/5 | 1/2 | 2/3 | 3/4 | 2/2 | 5/6 | 1/2 | 2/2 |
| Claude Haiku 5.5 · H† + Harness² step, Opus editor | 2/2 | 2/2 | 5/5 | 5/5 | 2/2 | 3/3 | 4/4 | 2/2 | 6/6 | 1/2 | 2/2 |

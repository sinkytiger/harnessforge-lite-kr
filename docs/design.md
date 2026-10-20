# Design: three harness papers, one agent

This project combines three October 2026 papers that the PyTorchKR weekly digest (2026/10/12–18) grouped
under one trend, "automatic evolution of agent harnesses and explicit state management":

| Paper | What it contributes here | Time scale |
|---|---|---|
| **LongHarness** (arXiv:2610.13075) | The runtime: an explicit EvidenceBank with a lifecycle, a Conclusion State whose open gaps steer search, and source-span citation rules | inside one episode |
| **Harness²** (arXiv:2610.14224) | Test-time refinement without an answer key: Propose (invariant and domain editors), Probe, Compose, plus an experience library | per task, across a task stream |
| **Harmony Harness** (arXiv:2610.15150) | Offline multi-objective search: MOEA/D with Tchebycheff scalarization, scope-factorized operators, dynamic composition | across a labelled search split |

All three treat the *harness* (prompts, tool guidance, skills, gates, budgets) as the thing to improve
while the model stays frozen. They are complementary.

## How they fit together

```
                    offline, labelled search split                     online, unlabelled test tasks
 seed harness H0 ──► Harmony search (accuracy × cost, MOEA/D) ──► H† ──► Harness² step per task ──► answer
                         │  factorized operators                         │  propose invariant + domain
                         │  general / domain scopes                      │  probe both on the same task
                         ▼                                               │  compose from the contrast
                     Pareto front                                        ▼
                                                                   experience library (EXPERIENCE.md)
   every run of every harness is a LongHarness episode:
   search → read (span S#) → upsert evidence (E#) → revise → compute over E# → final with E# refs, gated
```

Three links make this more than three modules side by side.

1. **One scope split serves both evolution methods.** Harmony factorizes the genome into general and
   environment-specific components. Harness² proposes an invariant candidate and a domain-specific
   candidate. Here both use the same `general/` and `domain/dart/` folders, so a domain fix found by one
   loop is a domain fix for the other, and transfer mode (`--scopes general`) drops every domain component.
2. **LongHarness state is what makes Harness²'s probes legible without an answer key.** Harness² judges a
   candidate by behavioural contrast with the reference run. An explicit EvidenceBank turns that contrast
   into concrete, checkable signals: was a final accepted, which gates rejected it, did the cited value
   appear in the cited span, was a superseded or preliminary filing cited, how many gaps stayed open.
   `harnessforge/evolve/harness2.py::contrast` uses only these signals.
3. **Harmony's verification gates live inside the LongHarness runtime.** Harmony evolves verification
   gates as harness components. Here the gates (`value_in_source`, `require_compute_for_derived`,
   `correction_check`, `preliminary_check`, ...) are switches on the LongHarness tools, so turning one on
   is an ordinary harness edit that both loops can make.

## The domain: a synthetic DART-style corpus

LongHarness evaluates on OfficeQA, numeric questions over U.S. Treasury bulletins. The Korean analogue
is DART filings. The corpus is synthetic so that every gold answer and every trap is known exactly:

* 16 fictional companies, 93 filings, about 600k characters: annual reports (3 years each), 2026 Q1
  and half-year reports, six `[기재정정]` corrected annual reports, seven 잠정실적 preliminary disclosures.
* Each filing carries a notice that it is synthetic and unrelated to any real company.
* 51 questions (16 search, 35 test), split by company so no test fact can be memorised during search.
* Planted traps match the two LongHarness failure modes. *Evidence-state drift*: a figure that a
  correction filing replaced, a preliminary figure, the separate (별도) instead of the consolidated (연결)
  statement, the cumulative instead of the 3-month column. *Unbounded exploration*: long boilerplate
  with look-alike numbers, near-duplicate filings, confusable company names (한빛전자 vs 한빛전기).
* An oracle policy replays each gold computation through the same tools; the test suite and CI check that
  all 51 questions are answerable within the budget, with every gate on.

A second, larger set (v2: three splits, unanswerable questions, more filing types) and a small set built
from real DART filings are described in [benchmark_v2.md](benchmark_v2.md). Abstention is scored there:
an abstaining final answer needs no evidence ids, but only for questions that offer "알 수 없음".

## Deviations from the papers

| Paper feature | Here | Why |
|---|---|---|
| LongHarness keeps the full, uncompacted history | Last few turns as one-line summaries, the last observation in full, the latest read page, plus the explicit state block | An 8k-token local model |
| Harness = code and files (OpenCode/Codex) in Harness², a Python package in Harmony | Declarative files: prompt text, skills with triggers, bounded knobs, gate switches | A small editor model cannot break the runtime; edits are validated statically |
| Harmony objectives: functionality and security | Accuracy and token cost | No security oracle in this domain; cost is the natural trade-off for a laptop |
| Harmony three-stage validation | Schema, bounds, size and leakage checks | Edits are declarative |
| Harness² editor: a strong model (Claude Opus 4.8 in the paper) | Same small local model by default; `--editor-model` takes any Ollama model | Zero API cost |
| 100M-token corpora, professional benchmarks | ~0.6M characters, 51 synthetic questions | Laptop scale; synthetic for exact gold and traps |

## What is frozen

The corpus, the search index, the tool semantics, the scoring and the gold answers form the evaluator
interface. Evolution can change prompt text, tool guidance, skills, numeric knobs within bounds and gate
switches. It cannot change tools, scoring or data, and the leakage check rejects any harness text that
names a corpus company or contains a large specific figure.

## Model backends and run safety

* **Executors and editors are interchangeable clients** with one interface (`json_call`, `chat`, usage
  accounting). `qwen3:4b` and other Ollama models use JSON-schema constrained decoding; Claude models
  (`harnessforge/claude.py`) use structured outputs, an `effort` level and, where available, server-side
  refusal fallbacks.
* **Edit operations are a schema union.** Each operation (`append_text`, `write_skill`, `set_gate`, ...) is
  its own object with its own required fields. An earlier flat schema with every field optional let
  editors emit a `write_skill` without a body; the union removed that failure.
* **Outages stop runs instead of polluting them.** Quota, credential and connection errors raise
  `ModelUnavailable`. An episode is never cached as a cheap failure because the server was down.
* **Everything resumes.** Episodes are cached per (harness hash, question, seed, model). Harmony writes a
  checkpoint after every evaluated child and continues from it. Harness² skips tasks already in
  `records.jsonl`. `scripts/resume_all.sh` restarts every remaining step.

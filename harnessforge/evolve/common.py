"""Shared pieces for both evolution loops: cached evaluation, run signals and failure digests.

Two kinds of feedback are kept strictly apart:

* ``verifier_free_signals`` use only what the agent's own run exposes (was a final accepted, gate
  rejections, invalid actions, repeated searches, unresolved gaps, cited filing types, tokens).
  Harness^2's test-time loop sees only these.
* ``failure_digest(..., with_gold=True)`` adds gold answers and trap labels. Only Harmony's offline
  search on the *search* split uses it, as Harmony uses failing tests on its evolve split.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from ..harness import Harness, compose
from ..llm import LLMError
from ..runtime import LLMPolicy, run_episode
from ..runtime.agent import describe

TOKEN_CAP = 80_000


def flush_print(*args) -> None:
    print(*args, flush=True)  # tokens per episode at which efficiency reaches 0


class ModelUnavailable(RuntimeError):
    """The model server cannot serve requests (quota, outage, timeouts). Runs stop instead of
    recording these as agent failures or as unusable editor replies."""


class QuotaExhausted(ModelUnavailable):
    pass


class GuardedLLM:
    """Wraps an editor client so quota and transport failures surface as ModelUnavailable."""

    def __init__(self, llm) -> None:
        self.llm = llm

    def __getattr__(self, name):
        return getattr(self.llm, name)

    def json_call(self, *args, **kwargs):
        try:
            return self.llm.json_call(*args, **kwargs)
        except LLMError as exc:
            if exc.quota:
                raise QuotaExhausted(str(exc)) from exc
            if exc.fatal:
                raise ModelUnavailable(str(exc)) from exc
            raise


def tags(question_text: str) -> list[str]:
    """Coarse situation tags used to retrieve library entries (no gold information)."""
    t = question_text
    out = []
    for tag, pat in (("ratio_or_growth", r"률|비율|증가|비중"), ("quarter_3m", r"분기|3개월"),
                     ("cumulative", r"누적|상반기"), ("separate_basis", r"별도"), ("consolidated", r"연결"),
                     ("comparison", r"더 높은|더 낮은"), ("annual", r"사업연도"), ("final_figures", r"최종|확정")):
        if re.search(pat, t):
            out.append(tag)
    return out


def run_cached(corpus, index, harness: Harness, question: dict, client, out_dir: Path | None, seed: int,
               scopes=("general", "domain"), router: str = "keyword", tag: str = "") -> dict:
    """Run one episode, or load it if an identical (harness, question, seed, scopes) run exists."""
    path = None
    if out_dir is not None:
        model = re.sub(r"[^A-Za-z0-9.]+", "-", getattr(client, "name", "model")).strip("-")
        name = (f"{question['qid']}__{harness.hash}__s{seed}__{model}"
                f"{('__' + '-'.join(scopes)) if tuple(scopes) != ('general', 'domain') else ''}{tag}.json")
        path = Path(out_dir) / "runs" / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    instance = compose(harness, question["text"], scopes=scopes, router=router, llm=client if router == "llm" else None)
    try:
        traj = run_episode(corpus, index, question, instance, LLMPolicy(client))
    except LLMError as exc:
        if exc.quota:
            raise QuotaExhausted(str(exc)) from exc
        if exc.fatal:
            raise ModelUnavailable(str(exc)) from exc
        raise
    traj["seed"] = seed
    traj["model"] = getattr(client, "name", "?")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(traj, ensure_ascii=False), encoding="utf-8")
    return traj


def metrics(trajs: list[dict], token_cap: int = TOKEN_CAP) -> dict:
    n = max(len(trajs), 1)
    acc = sum(t["score"]["correct"] for t in trajs) / n
    tokens = sum(t["usage"]["total_tokens"] for t in trajs) / n
    return {"n": len(trajs), "accuracy": acc, "accepted": sum(t["summary"]["final_accepted"] for t in trajs) / n,
            "mean_tokens": tokens, "mean_turns": sum(t["summary"]["turns"] for t in trajs) / n,
            "efficiency": max(0.0, 1.0 - tokens / token_cap),
            "traps": dict(Counter(t["score"]["trap"] for t in trajs if t["score"].get("trap"))),
            "seconds": sum(t.get("seconds", 0) for t in trajs)}


def evaluate(corpus, index, harness: Harness, questions: list[dict], client_for_seed, seeds=(7,),
             out_dir: Path | None = None, scopes=("general", "domain"), token_cap: int = TOKEN_CAP,
             log=flush_print) -> tuple[dict, list[dict]]:
    trajs = []
    for seed in seeds:
        client = client_for_seed(seed)
        for q in questions:
            t = run_cached(corpus, index, harness, q, client, out_dir, seed, scopes)
            trajs.append(t)
            if log:
                log(f"    {q['qid']} s{seed}: {'OK ' if t['score']['correct'] else 'x  '} "
                    f"ans={t['summary']['answer']!r} turns={t['summary']['turns']} tok={t['usage']['total_tokens']}")
    return metrics(trajs, token_cap), trajs


def verifier_free_signals(traj: dict) -> dict:
    s = traj["summary"]
    sig = s.get("signals", {})
    return {"final_accepted": s["final_accepted"], "answer": s.get("answer"), "turns": s["turns"],
            "tokens": traj["usage"]["total_tokens"], "gate_rejections": s.get("gate_rejections", {}),
            "invalid_actions": sig.get("invalid_action", 0), "repeated_searches": sig.get("repeated_search", 0),
            "repeated_reads": sig.get("repeated_read", 0), "reads": sig.get("action:read", 0),
            "upserts": sig.get("admitted", 0), "computes": s.get("computes", 0),
            "value_not_in_source": sig.get("value_not_in_source", 0),
            "unresolved_at_end": s.get("unresolved_at_end", 0), "cited_filings": s.get("cited_doc_kinds", [])}


def deficiency(sig: dict) -> int:
    """A scalar count of visible process problems (lower is better). Not a correctness verifier."""
    return (0 if sig["final_accepted"] else 5) + sum(sig["gate_rejections"].values()) + sig["invalid_actions"] \
        + sig["repeated_searches"] + sig["repeated_reads"] + sig["value_not_in_source"]


def trace(traj: dict, max_steps: int = 12) -> str:
    lines = []
    steps = traj["steps"]
    if len(steps) > max_steps:
        keep = steps[:4] + steps[-(max_steps - 4):]
        skipped = len(steps) - len(keep)
    else:
        keep, skipped = steps, 0
    for i, s in enumerate(keep):
        if skipped and i == 4:
            lines.append(f"   ... {skipped} turns omitted ...")
        first = s["obs"].splitlines()[0][:110] if s["obs"] else ""
        lines.append(f"   T{s['turn']} {describe(s['action'])[:110]} -> {first}")
    return "\n".join(lines)


def run_digest(traj: dict, question: dict | None = None, with_gold: bool = False) -> str:
    sig = verifier_free_signals(traj)
    head = f"- {traj['qid']}: {traj.get('question_text') or (question or {}).get('text', '')[:110]}"
    out = [head, f"  outcome: {'final accepted' if sig['final_accepted'] else 'NO accepted final'}"
                 f"; answer={sig['answer']!r}; turns={sig['turns']}; tokens={sig['tokens']}"]
    if with_gold and question is not None:
        sc = traj["score"]
        gold = f"{question['gold']:.2f}" if question["answer_type"] == "number" else question["gold"]
        out.append(f"  gold={gold}; correct={sc['correct']}" + (f"; matched trap '{sc['trap']}'" if sc.get("trap") else ""))
    probs = {k: v for k, v in (("gate_rejections", sig["gate_rejections"]), ("invalid_actions", sig["invalid_actions"]),
                               ("repeated_searches", sig["repeated_searches"]), ("repeated_reads", sig["repeated_reads"]),
                               ("value_not_in_source", sig["value_not_in_source"])) if v}
    out.append(f"  process: reads={sig['reads']} upserts={sig['upserts']} computes={sig['computes']} "
               f"unresolved_at_end={sig['unresolved_at_end']} cited={sig['cited_filings']} problems={probs or 'none'}")
    out.append(trace(traj))
    return "\n".join(out)


def failure_digest(trajs: list[dict], questions: dict, with_gold: bool, max_items: int = 4) -> str:
    """Aggregate statistics plus a few failed episodes, worst first."""
    m = metrics(trajs)
    agg = Counter()
    for t in trajs:
        sig = verifier_free_signals(t)
        agg["no_final"] += not sig["final_accepted"]
        agg["invalid_actions"] += sig["invalid_actions"]
        agg["repeated_searches"] += sig["repeated_searches"]
        agg["value_not_in_source"] += sig["value_not_in_source"]
        for g, v in sig["gate_rejections"].items():
            agg[f"gate:{g}"] += v
    lines = [f"episodes={m['n']} accepted_final={m['accepted']:.2f} mean_turns={m['mean_turns']:.1f} "
             f"mean_tokens={m['mean_tokens']:.0f}" + (f" accuracy={m['accuracy']:.2f} traps={m['traps']}" if with_gold else ""),
             "totals: " + ", ".join(f"{k}={v}" for k, v in agg.most_common() if v)]
    bad = [t for t in trajs if not (with_gold and t["score"]["correct"])]
    if with_gold:
        bad.sort(key=lambda t: (t["score"]["correct"], t["summary"]["final_accepted"]))
    else:
        bad.sort(key=lambda t: t["summary"]["final_accepted"])
    for t in bad[:max_items]:
        lines.append(run_digest(t, questions.get(t["qid"]), with_gold))
    return "\n".join(lines)

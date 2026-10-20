"""Policies and the episode loop.

Context construction follows LongHarness (system instructions, task block, history, current-state
block), with one deliberate deviation: the paper keeps the full uncompacted history, which does not
fit an 8k-token local model. Here the prompt keeps the last `history_window` turns as one-line
summaries, the full text of the last observation, and the most recent read page. The explicit
state block (EvidenceBank, Conclusion State, spans, budget) is what keeps older work available.
"""

from __future__ import annotations

import time

from ..llm import LLMError, Usage
from ..retrieval import Index
from ..scoring import score
from .env import MODES, ResearchEnv

_STATEMENT = {"type": "object", "properties": {"text": {"type": "string"},
                                                "refs": {"type": "array", "items": {"type": "string"}},
                                                "value": {"type": "number"}, "unit": {"type": "string"}},
              "required": ["text", "refs"]}


def action_schema(mode: str, thought_chars: int = 240) -> dict:
    props: dict = {"thought": {"type": "string", "maxLength": int(thought_chars)},
                   "action": {"type": "string", "enum": list(MODES[mode])},
                   "query": {"type": "string"}, "company": {"type": "string"},
                   "doc_id": {"type": "string"}, "offset": {"type": "integer"},
                   "expression": {"type": "string"}, "answer": {"type": "string"}}
    if mode == "longharness":
        props.update({"statements": {"type": "array", "items": _STATEMENT}, "target": {"type": "string"},
                      "replacement": _STATEMENT, "refs": {"type": "array", "items": {"type": "string"}},
                      "unresolved": {"type": "array", "items": {"type": "string"}}})
    else:
        props["text"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": ["thought", "action"]}


def describe(action: dict) -> str:
    a = action.get("action", "?")
    if a == "search":
        return f'search("{action.get("query", "")}"' + (f', company={action["company"]}' if action.get("company") else "") + ")"
    if a == "read":
        return f'read({action.get("doc_id")}@{action.get("offset", 0)})'
    if a == "list_docs":
        return f'list_docs({action.get("company", "")})'
    if a == "upsert":
        sts = action.get("statements") or []
        if isinstance(sts, dict):
            sts = [sts]
        if not isinstance(sts, list):
            sts = []
        return "upsert(" + "; ".join(f"{str(s.get('text') or '')[:40]}={s.get('value')}"
                                     for s in sts[:3] if isinstance(s, dict)) + ")"
    if a == "revise":
        return f'revise({action.get("target")})'
    if a == "compute":
        return f'compute({action.get("expression", "")})'
    if a == "final":
        return f'final({action.get("answer")!r}, refs={action.get("refs", [])})'
    if a == "note":
        return f'note({str(action.get("text", ""))[:50]})'
    return a


def build_prompt(question: dict, env: ResearchEnv, history: list[dict], cfg: dict) -> str:
    max_turns = int(cfg["max_turns"])
    turn = env.turn + 1
    parts = [f"# Question\n{question['text']}\n{env.corpus_note()}",
             f"# Budget\nTurn {turn} of {max_turns}." + (" LAST TURN: call final now with your best answer." if turn >= max_turns else
                                                       " Two turns left: finish with compute/final." if turn >= max_turns - 2 else "")]
    st = []
    if env.mode == "longharness":
        act = env.bank.active()
        st.append("Evidence (active): " + ("none yet" if not act else ""))
        st += [f"  {e.brief()}" for e in act[-12:]]
        ina = env.bank.inactive()
        if ina:
            st.append("Retired (cannot be cited): " + ", ".join(
                f"{e.eid} {e.status}" + (f" by {e.replaced_by}" if e.replaced_by else "") for e in ina[-8:]))
        c = env.conclusions
        st.append("Unresolved: " + ("; ".join(c.unresolved) if c.unresolved else "(none listed)"))
        if c.established:
            st.append("Established: " + "; ".join(c.established))
        if c.hypotheses:
            st.append("Hypotheses: " + "; ".join(c.hypotheses))
        if env.registry.spans:
            st.append("Spans: " + ", ".join(f"{s.sid}={s.doc_id}[{s.start}-{s.end}]"
                                             for s in list(env.registry.spans.values())[-8:]))
    else:
        st.append("Notes: " + ("none yet" if not env.notes else ""))
        st += [f"  - {n}" for n in env.notes]
    if env.computes:
        st.append("Computed: " + "; ".join(f"{c['expr']} = {c['value']:,.4f}" for c in env.computes[-4:]))
    parts.append("# State\n" + "\n".join(st))
    win = int(cfg.get("history_window", 3))
    if history:
        recent = history[-win:]
        parts.append("# Recent turns\n" + "\n".join(
            f"T{h['turn']} {describe(h['action'])} -> {h['obs'].splitlines()[0][:150] if h['obs'] else ''}" for h in recent))
        parts.append("# Last observation\n" + history[-1]["obs"])
        if env.page and history[-1]["action"].get("action") != "read":
            parts.append("# Current page\n" + env.page["header"] + "\n" + env.page["text"])
    parts.append("Reply with ONE JSON action.")
    return "\n\n".join(parts)


class LLMPolicy:
    def __init__(self, client, max_tokens: int = 700) -> None:
        self.client = client
        self.max_tokens = max_tokens

    def act(self, question: dict, instance, env: ResearchEnv, history: list[dict]) -> tuple[dict, Usage, str]:
        prompt = build_prompt(question, env, history, instance.config)
        messages = [{"role": "system", "content": instance.system}, {"role": "user", "content": prompt}]
        schema = action_schema(env.mode, int(instance.config.get("thought_chars", 240)))
        total = Usage()
        raw = ""
        for attempt in range(2):
            try:
                raw, u = self.client.chat(messages, schema=schema, max_tokens=self.max_tokens,
                                          temperature=None if attempt == 0 else 0.0)
            except LLMError as exc:
                # A quota or an unreachable server is not the agent's fault: stop the episode so it
                # is not cached as a cheap failure. Other errors count as one invalid action.
                if exc.fatal:
                    raise
                raw = f"model call failed: {exc}"
                continue
            total.add(u)
            try:
                from ..llm import extract_json
                action = extract_json(raw)
                if isinstance(action.get("action"), str):
                    return action, total, raw
            except LLMError:
                continue
        return {"action": "invalid", "thought": "unparsable reply"}, total, raw


class OraclePolicy:
    """Replays the gold computation through the tools. It proves each question is answerable inside
    the budget and that the gates accept a correct, well-cited answer. It is not a baseline."""

    def __init__(self, question: dict, search_first: bool = True) -> None:
        self.q = question
        self.plan: list = []
        self.search_first = search_first
        self._built = False
        self.fact_eids: dict[int, str] = {}

    def _facts(self) -> list[tuple[int, dict]]:
        calc = self.q["calc"]
        if calc.get("abstain"):
            return []
        if "compare" in calc:
            out, i = [], 0
            for item in calc["compare"]:
                for f in item["facts"]:
                    out.append((i, f))
                    i += 1
            return out
        return list(enumerate(calc["facts"]))

    def act(self, question: dict, instance, env: ResearchEnv, history: list[dict]):
        u = Usage()
        if self.q["calc"].get("abstain"):
            if not env.search_log:
                return {"action": "search", "query": self.q["companies"][0] + " 매출액"}, u, ""
            return {"action": "final", "answer": "알 수 없음", "refs": []}, u, ""
        if not self._built:
            self._built = True
            first = self._facts()[0][1]
            if self.search_first:
                company = env.corpus.by_id[first["doc_id"]]["company"]
                self.plan.append({"action": "search", "query": f"{company} {first['key'][2]}", "company": company})
            for i, f in self._facts():
                self.plan.append(("read_and_upsert", i, f))
            self.plan.append(("compute_and_final",))
        step = self.plan.pop(0) if self.plan else ("compute_and_final",)
        if isinstance(step, dict):
            return step, u, ""
        if step[0] == "read_and_upsert":
            _, i, f = step
            covering = [s for s in env.registry.spans.values()
                        if s.doc_id == f["doc_id"] and s.start <= f["offset"] < s.end - 1]
            if not covering:
                self.plan.insert(0, step)
                return {"action": "read", "doc_id": f["doc_id"], "offset": f["line_start"]}, u, ""
            span = covering[-1]
            # admit every pending fact printed on this page in one upsert (the tool takes up to 4)
            batch = [(i, f)]
            while self.plan and len(batch) < 4 and isinstance(self.plan[0], tuple) and self.plan[0][0] == "read_and_upsert":
                _, j, g = self.plan[0]
                if g["doc_id"] == span.doc_id and span.start <= g["offset"] < span.end - 1:
                    batch.append((j, g))
                    self.plan.pop(0)
                else:
                    break
            statements = []
            for n, (j, g) in enumerate(batch):
                self.fact_eids[j] = f"E{len(env.bank.entries) + 1 + n}"
                key = g["key"]
                statements.append({"text": f"{key[1]} {key[2]} {key[3]}", "refs": [span.sid],
                                   "value": g["printed"], "unit": g["unit"]})
            return {"action": "upsert", "statements": statements, "unresolved": ["none"]}, u, ""
        calc = self.q["calc"]
        if "compare" in calc:
            done = [c for c in env.computes]
            items = calc["compare"]
            offset = sum(len(it["facts"]) for it in items[:len(done)])
            if len(done) < len(items):
                it = items[len(done)]
                expr = self._sub(it["expr"], offset)
                self.plan.insert(0, ("compute_and_final",))
                return {"action": "compute", "expression": expr}, u, ""
            vals = [c["value"] for c in done[-len(items):]]
            ranked = sorted(range(len(items)), key=lambda k: -vals[k])
            best = items[ranked[1] if calc.get("pick") == "second" else ranked[0]]["name"]
            return {"action": "final", "answer": best, "refs": list(self.fact_eids.values())}, u, ""
        if not env.computes:
            self.plan.insert(0, ("compute_and_final",))
            return {"action": "compute", "expression": self._sub(calc["expr"], 0)}, u, ""
        v = env.computes[-1]["value"]
        ans = f"{v:.2f}" if self.q["unit"] == "%" else f"{v:.1f}"
        return {"action": "final", "answer": ans, "refs": list(self.fact_eids.values())}, u, ""

    def _sub(self, expr: str, offset: int) -> str:
        import re
        return re.sub(r"F(\d+)", lambda m: self.fact_eids[int(m.group(1)) + offset], expr)


def run_episode(corpus, index: Index, question: dict, instance, policy, max_turns: int | None = None,
                keep_prompts: bool = False) -> dict:
    env = ResearchEnv(corpus, index, question, instance.config, instance.gates, instance.mode)
    max_turns = int(max_turns or instance.config["max_turns"])
    history: list[dict] = []
    usage = Usage()
    t0 = time.time()
    while env.turn < max_turns and not env.done:
        action, u, raw = policy.act(question, instance, env, history)
        usage.add(u)
        obs = env.step(action)
        rec = {"turn": env.turn, "action": action, "obs": obs, "tokens": u.total_tokens}
        if keep_prompts:
            rec["raw"] = raw
        history.append(rec)
    summary = env.summary()
    result = score(question, env.final_answer)
    return {"qid": question["qid"], "qtype": question["qtype"], "split": question["split"],
            "harness": instance.harness_hash, "skills": instance.skills, "scopes": list(instance.scopes),
            "mode": instance.mode, "summary": summary, "score": result,
            "usage": usage.to_json() | {"total_tokens": usage.total_tokens},
            "seconds": round(time.time() - t0, 2), "steps": history}


def run_direct(corpus, index: Index, question: dict, client, k: int = 6) -> dict:
    """Retrieve-then-answer baseline: top-k chunks for the question, one model call, no tools."""
    hits = index.search(question["text"], k=k, snippet_chars=60)
    blocks = []
    for h in hits:
        d = corpus.by_id[h["doc_id"]]
        start = d["text"].rfind("\n", 0, max(h["offset"] - 200, 0)) + 1
        blocks.append(f"[{h['doc_id']} 「{h['title']}」]\n{d['text'][start:start + 700]}")
    prompt = (f"Question: {question['text']}\n\nExcerpts from the filings corpus:\n\n" + "\n\n".join(blocks) +
              "\n\nAnswer from the excerpts. Reply as JSON: {\"answer\": \"...\"}")
    schema = {"type": "object", "properties": {"thought": {"type": "string", "maxLength": 320},
                                               "answer": {"type": "string", "maxLength": 60}},
              "required": ["thought", "answer"]}
    t0 = time.time()
    usage = Usage()
    try:
        out, u = client.json_call("You answer questions about Korean corporate filings precisely.", prompt, schema,
                                  max_tokens=600)
        usage.add(u)
        answer = str(out.get("answer", "")).strip() or None
    except LLMError as exc:
        if exc.fatal:
            raise
        answer = None
    result = score(question, answer)
    return {"qid": question["qid"], "qtype": question["qtype"], "split": question["split"], "harness": "direct",
            "skills": [], "scopes": [], "mode": "direct",
            "summary": {"final_accepted": answer is not None, "answer": answer, "turns": 1,
                        "docs_read": [h["doc_id"] for h in hits], "gate_rejections": {}, "signals": {}},
            "score": result, "usage": usage.to_json() | {"total_tokens": usage.total_tokens},
            "seconds": round(time.time() - t0, 2), "steps": []}

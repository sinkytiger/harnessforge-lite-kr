"""The research environment: tools, budgets and verification gates.

The environment never sees the gold answer. Gates are part of the *harness*: each one can be
switched on or off by the harness configuration, and domain gates exist only when the domain
scope is composed in (Harmony Harness keeps general and domain components apart).

Modes
-----
* ``longharness``: search, list_docs, read, upsert, revise, compute, final (explicit state).
* ``notes``: search, list_docs, read, note, compute, final. Free-text working notes replace the
  EvidenceBank, as in the paper's "generic free-text working notes" ablation.
"""

from __future__ import annotations

import re
from collections import Counter

from ..calc import CalcError, evaluate, names_in
from ..retrieval import Index
from ..scoring import is_abstain, parse_number
from .state import ConclusionState, Evidence, EvidenceBank, SourceRegistry

GENERAL_GATES = {
    "numeric_answer": True,          # a question that asks for a number must get a number
    "require_refs": True,            # final must cite at least one evidence id
    "cite_active_only": True,        # final/compute may cite only active evidence
    "value_in_source": False,        # a numeric statement's value must appear in its cited span
    "require_compute_for_derived": False,  # ratios, growth, shares, comparisons need a compute first
    "block_repeats": False,          # refuse an identical search or a re-read of the same page
}
DOMAIN_GATES = {
    "correction_check": False,       # reject citations of a filing that a [기재정정] filing replaced
    "preliminary_check": False,      # reject citations of 잠정 (preliminary) figures
    "unit_declared": False,          # numeric statements must declare their unit
}
KNOWN_UNITS = {"원", "천원", "백만원", "억원", "조원", "%", "주", "명"}
MODES = {
    "longharness": ("search", "list_docs", "read", "upsert", "revise", "compute", "final"),
    "notes": ("search", "list_docs", "read", "note", "compute", "final"),
}
DERIVED = re.compile(r"률|비율|증가|감소|비중|더 높은|더 낮은")


def _as_list(x) -> list:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def value_variants(v: float) -> list[str]:
    a = abs(v)
    out = []
    if float(a).is_integer():
        out += [f"{int(a):,}", str(int(a))]
    else:
        out += [f"{a:,}", f"{a}", f"{a:,.1f}", f"{a:,.2f}"]
    return out


def value_in_text(v: float, text: str) -> bool:
    """True when the number appears as a whole figure (not inside a longer number)."""
    return any(re.search(r"(?<![\d,.])" + re.escape(s) + r"(?![\d]|[,.]\d)", text) for s in value_variants(v))


class ResearchEnv:
    def __init__(self, corpus, index: Index, question: dict, config: dict, gates: dict,
                 mode: str = "longharness") -> None:
        self.corpus = corpus
        self.index = index
        self.qid = question["qid"]
        self.question_text = question["text"]
        self.cfg = config
        self.gates = gates
        self.mode = mode
        self.allowed = MODES[mode]
        self.registry = SourceRegistry()
        self.bank = EvidenceBank()
        self.conclusions = ConclusionState()
        self.notes: list[str] = []
        self.computes: list[dict] = []
        self.turn = 0
        self.done = False
        self.final_answer = None
        self.final_refs: list[str] = []
        self.page: dict | None = None   # the most recent read, kept visible to the policy
        self.signals = Counter()
        self.gate_rejections = Counter()
        self.search_log: list[str] = []
        self.search_turns: dict[str, int] = {}
        self.docs_read: list[str] = []

    # ------------------------------------------------------------------ helpers
    def corpus_note(self) -> str:
        """Environment facts for the task block (no answer information)."""
        docs = self.corpus.docs
        dates = sorted(d["filed"] for d in docs)
        n_co = len({d["company"] for d in docs})
        return (f"(Corpus: {len(docs)} published filings of {n_co} companies, filed {dates[0]} to {dates[-1]}. "
                "They are all past, published facts.)")

    @property
    def expects_number(self) -> bool:
        return "숫자만" in self.question_text

    @property
    def allows_abstain(self) -> bool:
        return "알 수 없음" in self.question_text

    @property
    def derived(self) -> bool:
        return bool(DERIVED.search(self.question_text))

    def span_text(self, sid: str) -> str:
        s = self.registry.spans[sid]
        return self.corpus.by_id[s.doc_id]["text"][s.start:s.end]

    def _reject(self, gate: str, msg: str) -> str:
        self.gate_rejections[gate] += 1
        return f"REJECTED by gate '{gate}': {msg}"

    # ------------------------------------------------------------------ dispatch
    def step(self, action: dict) -> str:
        self.turn += 1
        name = str(action.get("action", "")).strip()
        self.signals[f"action:{name or 'none'}"] += 1
        if name not in self.allowed:
            self.signals["invalid_action"] += 1
            return f"ERROR: unknown action '{name}'. Allowed: {', '.join(self.allowed)}."
        try:
            obs = getattr(self, f"_a_{name}")(action)
        except (KeyError, ValueError, TypeError, CalcError) as exc:
            self.signals["invalid_action"] += 1
            obs = f"ERROR: {exc}"
        if self.mode == "longharness" and name not in ("upsert", "revise"):
            if self.conclusions.update(action):
                self.signals["conclusion_updates"] += 1
        return obs

    # ------------------------------------------------------------------ tools
    def _a_search(self, a: dict) -> str:
        query = str(a.get("query") or "").strip()
        if not query:
            raise ValueError("search needs a non-empty 'query'")
        company = str(a.get("company") or "").strip() or None
        doc_id = str(a.get("doc_id") or "").strip().upper() or None
        key = f"{query.lower()}|{company or ''}|{doc_id or ''}"
        if key in self.search_log:
            self.signals["repeated_search"] += 1
            if self.gates.get("block_repeats"):
                return self._reject("block_repeats", f'you already ran search("{query}") at turn '
                                    f"{self.search_turns[key]}; read one of its results (doc_id + offset) or change the query")
        self.search_log.append(key)
        self.search_turns.setdefault(key, self.turn)
        k, sn = int(self.cfg["search_k"]), int(self.cfg["snippet_chars"])
        if query.startswith("re:"):
            hits = self.index.regex(query[3:], k=k, company=company, doc_id=doc_id, snippet_chars=sn)
        else:
            hits = self.index.search(query, k=k, company=company, doc_id=doc_id, snippet_chars=sn)
        if not hits:
            self.signals["empty_search"] += 1
            return f'search("{query}") -> no results. Try other words or list_docs.'
        lines = [f'search("{query}") -> {len(hits)} results (snippets are for navigation; read before citing)']
        for i, h in enumerate(hits, 1):
            lines.append(f"{i}. {h['doc_id']} 「{h['title']}」 {h['section'][:30]} @offset {h['offset']}: {h['snippet']}")
        return "\n".join(lines)

    def _a_list_docs(self, a: dict) -> str:
        company = str(a.get("company") or a.get("query") or "").strip()
        docs = [d for d in self.corpus.docs if company and company in d["company"]]
        if not docs:
            names = sorted({d["company"] for d in self.corpus.docs})
            return f"list_docs: no company matches '{company}'. Companies: {', '.join(names)}"
        docs.sort(key=lambda d: d["filed"])
        lines = [f"list_docs('{company}') -> {len(docs)} filings (oldest first)"]
        for d in docs:
            lines.append(f"{d['doc_id']} 「{d['company']} | {d['report']} | 제출 {d['filed']}」 {len(d['text']):,} chars")
        return "\n".join(lines)

    def _doc_id(self, a: dict) -> str:
        """The doc id, also accepted from another field when a small model misplaces it."""
        for key in ("doc_id", "target", "query"):
            m = re.search(r"\bD\d{3}\b", str(a.get(key) or "").upper())
            if m:
                if key != "doc_id":
                    self.signals["doc_id_misplaced"] += 1
                return m.group(0)
        return str(a.get("doc_id") or "").strip().upper()

    def _a_read(self, a: dict) -> str:
        doc_id = self._doc_id(a)
        if doc_id not in self.corpus.by_id:
            raise ValueError(f"unknown doc_id '{doc_id}'")
        text = self.corpus.by_id[doc_id]["text"]
        try:
            offset = int(a.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, min(offset, max(len(text) - 1, 0)))
        # Start a few lines above the requested offset, so a hit inside a table comes with the
        # table's title, unit line and column header.
        lead = min(360, int(self.cfg["read_chars"]) // 3)
        anchor = max(0, offset - lead)
        start = text.rfind("\n", 0, anchor) + 1 if anchor else 0
        end = min(len(text), start + int(self.cfg["read_chars"]))
        nl = text.rfind("\n", start, end)
        if end < len(text) and nl > start:
            end = nl + 1
        prior = [s for s in self.registry.spans.values() if s.doc_id == doc_id and s.start == start]
        if prior:
            self.signals["repeated_read"] += 1
            if self.gates.get("block_repeats"):
                return self._reject("block_repeats", f"you already read this page as {prior[0].sid}; use it, "
                                    "or read another offset or document")
        span = self.registry.register(doc_id, start, end, self.turn)
        self.docs_read.append(doc_id)
        d = self.corpus.by_id[doc_id]
        header = f"{span.sid} = {doc_id} chars {start}-{end} of {len(text)} 「{d['company']} | {d['report']} | 제출 {d['filed']}」"
        self.page = {"sid": span.sid, "header": header, "text": text[start:end]}
        more = f"\n[continue with read(doc_id={doc_id}, offset={end + lead})]" if end < len(text) else "\n[end of document]"
        return header + "\n" + text[start:end] + more

    def _statement(self, st: dict) -> tuple[str, list[str], float | None, str | None, bool | None]:
        if not isinstance(st, dict):
            raise ValueError("each statement must be an object with text and refs")
        text = str(st.get("text") or "").strip()
        refs = [str(r).strip().upper() for r in _as_list(st.get("refs")) if str(r).strip()]
        if not text:
            raise ValueError("statement text is empty")
        if not refs:
            raise ValueError(f"statement '{text[:40]}' has no refs; cite span ids such as S1")
        bad = [r for r in refs if r not in self.registry.spans]
        if bad:
            raise ValueError(f"refs {bad} are not registered spans; only spans returned by read can be cited")
        value = st.get("value")
        if value is not None and not isinstance(value, (int, float)):
            value = parse_number(value)
        unit = (str(st.get("unit")).strip() or None) if st.get("unit") is not None else None
        found = None
        if value is not None:
            found = any(value_in_text(float(value), self.span_text(r)) for r in refs)
        return text, refs, (None if value is None else float(value)), unit, found

    def _check_statement(self, value, unit, found) -> str | None:
        if self.gates.get("value_in_source") and value is not None and not found:
            return self._reject("value_in_source", f"value {value:,.6g} does not appear in the cited span text; "
                                "copy the number exactly as printed and keep the table's unit")
        if self.gates.get("unit_declared") and value is not None and unit not in KNOWN_UNITS:
            return self._reject("unit_declared", f"unit '{unit}' is missing or unknown; use one of {sorted(KNOWN_UNITS)}")
        return None

    def _a_upsert(self, a: dict) -> str:
        sts = a.get("statements") or []
        if isinstance(sts, dict):
            sts = [sts]
        if not sts:
            raise ValueError("upsert needs 'statements': [{text, refs, value, unit}]")
        out = []
        for st in sts[:4]:
            try:
                text, refs, value, unit, found = self._statement(st)
            except ValueError as exc:
                self.signals["rejected_statement"] += 1
                out.append(f"rejected: {exc}")
                continue
            if (msg := self._check_statement(value, unit, found)):
                self.signals["rejected_statement"] += 1
                out.append(msg)
                continue
            ev = self.bank.admit(text, refs, value, unit, self.turn, found)
            self.signals["admitted"] += 1
            if found is False:
                self.signals["value_not_in_source"] += 1
            out.append(f"{ev.eid} admitted (active): {ev.brief()}")
        return "\n".join(out)

    def _a_revise(self, a: dict) -> str:
        target = str(a.get("target") or "").strip().upper()
        ev = self.bank.entries.get(target)
        if ev is None or ev.status != "active":
            raise ValueError(f"'{target}' is not an active evidence id")
        repl = a.get("replacement")
        if not repl and a.get("statements"):
            repl = (a.get("statements") or [None])[0]
        if repl:
            text, refs, value, unit, found = self._statement(repl)
            if (msg := self._check_statement(value, unit, found)):
                return msg
            new = self.bank.admit(text, refs, value, unit, self.turn, found, replaces=target)
            self.bank.revise(target, new, self.turn)
            self.signals["superseded"] += 1
            return f"{target} superseded by {new.eid}: {new.brief()}"
        self.bank.revise(target, None, self.turn)
        self.signals["retracted"] += 1
        return f"{target} retracted"

    def _a_compute(self, a: dict) -> str:
        expr = str(a.get("expression") or "").strip()
        names = names_in(expr)
        env: dict[str, float] = {}
        if self.mode == "notes" and names:
            raise ValueError("in notes mode compute takes numbers only, e.g. 1234 / 5678 * 100")
        for n in names:
            ev = self.bank.entries.get(n)
            if ev is None:
                raise ValueError(f"unknown evidence id {n}")
            if self.gates.get("cite_active_only") and ev.status != "active":
                self._reject("cite_active_only", f"{n} is {ev.status}")
                raise ValueError(f"{n} is {ev.status}; cite the active replacement instead")
            if ev.value is None:
                raise ValueError(f"{n} has no numeric value")
            env[n] = ev.value
        value = evaluate(expr, env)
        self.computes.append({"expr": expr, "value": value, "refs": names, "turn": self.turn})
        self.signals["computes"] += 1
        return f"compute({expr}) = {value:,.6f}" + (f" using {', '.join(names)}" if names else "")

    def _a_note(self, a: dict) -> str:
        text = str(a.get("text") or a.get("thought") or "").strip()
        if not text:
            raise ValueError("note needs 'text'")
        self.notes.append(text[:240])
        self.notes = self.notes[-10:]
        return f"note saved ({len(self.notes)} notes)"

    def _a_final(self, a: dict) -> str:
        answer = a.get("answer")
        if isinstance(answer, (int, float)) and not isinstance(answer, bool):
            answer = f"{answer}"
        answer = str(answer or "").strip()
        refs = [str(r).strip().upper() for r in _as_list(a.get("refs")) if str(r).strip()]
        if not answer:
            raise ValueError("final needs 'answer'")
        if self.allows_abstain and is_abstain(answer):
            # "cannot be determined from the filings" needs no evidence ids
            self.done = True
            self.final_answer = answer
            self.final_refs = refs
            self.signals["final_accepted"] += 1
            self.signals["abstained"] += 1
            return f"final accepted: {answer}"
        if self.gates.get("numeric_answer") and self.expects_number and parse_number(answer) is None:
            return self._reject("numeric_answer", "the question asks for a number only")
        if self.mode == "longharness":
            if self.gates.get("require_refs") and not refs:
                return self._reject("require_refs", "cite the active evidence ids (E...) that support the answer")
            if self.gates.get("cite_active_only"):
                bad = [r for r in refs if r not in self.bank.entries or self.bank.entries[r].status != "active"]
                if bad:
                    return self._reject("cite_active_only", f"{bad} are not active evidence ids")
            if self.gates.get("require_compute_for_derived") and self.derived and not self.computes:
                return self._reject("require_compute_for_derived",
                                    "this answer is derived from several figures; run compute over evidence ids first")
            docs = {self.registry.spans[s].doc_id for r in refs if r in self.bank.entries
                    for s in self.bank.entries[r].refs}
            for doc_id in sorted(docs):
                d = self.corpus.by_id[doc_id]
                if self.gates.get("correction_check") and d.get("corrected_by"):
                    c = self.corpus.by_id[d["corrected_by"]]
                    return self._reject("correction_check",
                                        f"{doc_id} was replaced by {c['doc_id']} 「{c['report']} | 제출 {c['filed']}」; "
                                        "read the corrected filing and revise the evidence")
                if self.gates.get("preliminary_check") and d["kind"] in ("prelim", "prelim_correction"):
                    return self._reject("preliminary_check",
                                        f"{doc_id} is a preliminary (잠정) disclosure; use the audited report")
        self.done = True
        self.final_answer = answer
        self.final_refs = refs
        self.signals["final_accepted"] += 1
        return f"final accepted: {answer}"

    # ------------------------------------------------------------------ summary
    def summary(self) -> dict:
        cited_docs = sorted({self.registry.spans[s].doc_id for r in self.final_refs if r in self.bank.entries
                             for s in self.bank.entries[r].refs})
        vf = [e.value_found for e in self.bank.entries.values() if e.value_found is not None]
        return {
            "final_accepted": self.done,
            "answer": self.final_answer,
            "refs": self.final_refs,
            "cited_docs": cited_docs,
            "cited_doc_kinds": [self.corpus.by_id[d]["report"] for d in cited_docs],
            "turns": self.turn,
            "unresolved_at_end": len(self.conclusions.unresolved),
            "active_evidence": len(self.bank.active()),
            "inactive_evidence": len(self.bank.inactive()),
            "value_found_rate": (sum(vf) / len(vf)) if vf else None,
            "computes": len(self.computes),
            "gate_rejections": dict(self.gate_rejections),
            "signals": dict(self.signals),
            "docs_read": list(dict.fromkeys(self.docs_read)),
            "notes": len(self.notes),
        }

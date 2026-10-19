"""Verifier-free test-time harness refinement (Harness^2, arXiv:2610.14224, simplified).

Task-level step Φ for one task q and harness H:
  1. Reference: run H once (k times in parallel mode).
  2. Propose: an *invariant* editor (scope general) and a *domain* editor (scope domain) each edit H.
  3. Probe: run each candidate on the same task with the same model and seed.
  4. Compose: an editor reads the reference, the candidates, their diffs and the probe runs, and
     keeps, adopts one, or merges both. The composed harness is run to get the deliverable.
  With k > 1 (parallel), k compose sessions run and an anonymised selector picks one deliverable.

Harnessing-level recursion: after each task, edits whose probe evidence shows a contrast (a
visible deficiency fixed without a new one) become library entries (EXPERIENCE.md + ops.json).
Later tasks start again from H0, but their propose and compose prompts can read the library.

No answer key is used anywhere in this loop. Scores are attached only afterwards, for reporting.
Here the "contrast" comes from the explicit LongHarness state: accepted final, gate rejections,
values missing from the cited source, outdated or preliminary filings cited, repeated searches.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..harness import EditError, Harness
from . import editor as E
from .common import flush_print, GuardedLLM, ModelUnavailable, QuotaExhausted, deficiency, run_cached, run_digest, tags, verifier_free_signals


def _statement_texts(run: dict) -> list[str]:
    """Evidence statement texts from a run, tolerant of malformed actions."""
    out = []
    for st in run.get("steps", []):
        a = st.get("action") or {}
        if a.get("action") != "upsert":
            continue
        sts = a.get("statements")
        sts = [sts] if isinstance(sts, dict) else sts if isinstance(sts, list) else []
        out += [str(x.get("text") or "")[:60] for x in sts if isinstance(x, dict)]
    return out


@dataclass
class Library:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        idx = self.root / "index.json"
        self.entries: list[dict] = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []

    def relevant(self, question_text: str, k: int = 3) -> list[dict]:
        t = set(tags(question_text))
        scored = sorted(self.entries, key=lambda e: (-len(t & set(e.get("tags", []))), -e.get("support", 0)))
        return [e for e in scored if t & set(e.get("tags", []))][:k] or scored[:1]

    def add(self, entry: dict) -> None:
        entry["id"] = f"X{len(self.entries) + 1:03d}"
        d = self.root / entry["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "ops.json").write_text(json.dumps(entry["ops"], ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "EXPERIENCE.md").write_text(
            f"# {entry['id']}\n\n**Situation.** {entry['situation']}\n\n**Lesson.** {entry['lesson']}\n\n"
            f"**Edit.** {'; '.join(entry['applied'])}\n\n```diff\n{entry.get('diff', '')}\n```\n\n"
            f"**Evidence.** {entry['evidence']}\n\n"
            f"**Tags.** {', '.join(entry['tags'])} (from task {entry['task']})\n", encoding="utf-8")
        self.entries.append(entry)
        (self.root / "index.json").write_text(json.dumps(self.entries, ensure_ascii=False, indent=1), encoding="utf-8")


def contrast(before: dict, after: dict) -> tuple[bool, str]:
    """Deterministic support check from verifier-free signals."""
    b, a = verifier_free_signals(before), verifier_free_signals(after)
    db, da = deficiency(b), deficiency(a)
    if a["final_accepted"] and not b["final_accepted"]:
        return True, f"final accepted after the edit (before: none); deficiency {db} -> {da}"
    if not a["final_accepted"] and b["final_accepted"]:
        return False, "the edit lost the accepted final"
    if da + 2 <= db:
        return True, f"process deficiencies {db} -> {da}"
    if a["final_accepted"] and a["answer"] == b["answer"] and a["tokens"] < 0.7 * b["tokens"]:
        return True, f"same answer with {b['tokens']} -> {a['tokens']} tokens"
    if da > db:
        return False, f"process deficiencies grew {db} -> {da}"
    return False, f"no clear contrast (deficiency {db} -> {da})"


class Harness2:
    def __init__(self, corpus, index, client_for_seed, editor_llm, out_dir: Path, k: int = 1,
                 use_library: bool = True, library_dir: Path | None = None, seed: int = 7, log=flush_print) -> None:
        self.corpus, self.index = corpus, index
        self.client_for_seed = client_for_seed
        self.editor = GuardedLLM(editor_llm)
        self.out = Path(out_dir)
        self.k = k
        self.use_library = use_library
        self.library = Library(Path(library_dir) if library_dir else self.out / "library")
        self.seed = seed
        self.log = log
        self.forbidden = sorted({c["name"] for c in corpus.companies})
        self.editor_calls = 0
        self.exec_tokens = 0

    def _run(self, h: Harness, q: dict, seed: int, tag: str = "") -> dict:
        t = run_cached(self.corpus, self.index, h, q, self.client_for_seed(seed), self.out, seed, tag=tag)
        self.exec_tokens += t["usage"]["total_tokens"]
        return t

    def _editor_tokens(self) -> int:
        u = getattr(self.editor, "usage", None)
        return int(getattr(u, "total_tokens", 0) or 0)

    def _propose(self, kind: str, q: dict, h0: Harness, ref: dict) -> dict:
        scope = "general" if kind == "invariant" else "domain"
        lib = self.library.relevant(q["text"]) if self.use_library else []
        prompt = E.propose_prompt(kind, q["text"], h0.summary(), run_digest(ref, q, with_gold=False), lib)
        error = None
        ops: list = []
        for attempt in range(2):
            p = prompt + (f"\n\nYOUR PREVIOUS EDIT WAS REJECTED: {error}" if error else "")
            self.editor_calls += 1
            try:
                out, _ = self.editor.json_call(E.EDITOR_SYSTEM, p, E.op_schema(E.OPS_BY_COMPONENT["any"], scope),
                                               max_tokens=900)
            except ModelUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                error = f"reply was not valid JSON ({exc})"
                continue
            ops = out.get("ops") or []
            try:
                child, applied = h0.apply(ops, scope=scope, forbidden_terms=self.forbidden)
                return {"kind": kind, "harness": child, "ops": ops, "applied": applied,
                        "rationale": out.get("rationale", ""), "diff": h0.diff(child)}
            except EditError as exc:
                error = str(exc)
        return {"kind": kind, "harness": None, "ops": ops, "applied": [], "rationale": "", "error": error}

    def step(self, q: dict, h0: Harness) -> dict:
        """One task-level step at budget k. Returns the record ξ and the deliverable trajectory."""
        seeds = [self.seed + j for j in range(self.k)]
        exec0, ed0, calls0 = self.exec_tokens, self._editor_tokens(), self.editor_calls
        usd0 = float(getattr(self.editor, "usd", 0.0))
        refs = [self._run(h0, q, s) for s in seeds]
        composed: list[tuple[Harness, dict, dict]] = []
        pool: list[dict] = []
        for j, s in enumerate(seeds):
            for kind in ("invariant", "domain"):
                c = self._propose(kind, q, h0, refs[j])
                c["seed_index"] = j
                if c["harness"] is not None:
                    c["probe"] = self._run(c["harness"], q, s)
                    c["digest"] = run_digest(c["probe"], q, with_gold=False)
                    c["contrast"] = contrast(refs[j], c["probe"])
                pool.append(c)
        for j, s in enumerate(seeds):
            mine = [c for c in pool if c["seed_index"] == j]
            cands = [c for c in mine if c["harness"] is not None] or mine
            self.editor_calls += 1
            try:
                dec, _ = self.editor.json_call(E.EDITOR_SYSTEM,
                                               E.compose_prompt(q["text"], run_digest(refs[j], q), cands),
                                               E.COMPOSE_SCHEMA, max_tokens=500)
            except ModelUnavailable:
                raise
            except Exception:  # noqa: BLE001
                dec = {"decision": "keep", "rationale": "editor reply unusable"}
            decision = dec.get("decision", "keep")
            inv = next((c for c in mine if c["kind"] == "invariant" and c["harness"] is not None), None)
            dom = next((c for c in mine if c["kind"] == "domain" and c["harness"] is not None), None)
            h_new, run, applied, ops = h0, refs[j], [], []
            if decision == "adopt_invariant" and inv:
                h_new, run, applied, ops = inv["harness"], inv["probe"], inv["applied"], inv["ops"]
            elif decision == "adopt_domain" and dom:
                h_new, run, applied, ops = dom["harness"], dom["probe"], dom["applied"], dom["ops"]
            elif decision == "merge" and (inv or dom):
                h_new = h0
                for c in (inv, dom):
                    if c is None:
                        continue
                    try:
                        h_new, a = h_new.apply(c["ops"], scope="general" if c["kind"] == "invariant" else "domain",
                                               forbidden_terms=self.forbidden)
                        applied += a
                        ops += c["ops"]
                    except EditError:
                        pass
                run = self._run(h_new, q, s, tag="__composed") if h_new.hash != h0.hash else refs[j]
            else:
                decision = "keep"
            composed.append((h_new, run, {"decision": decision, "rationale": dec.get("rationale", ""),
                                          "applied": applied, "ops": ops, "ref_index": j}))

        choice = 0
        if len(composed) > 1:
            deliverables = []
            for _, run, _ in composed:
                s = run["summary"]
                ev = "; ".join(_statement_texts(run))
                deliverables.append(f"answer: {s.get('answer')!r}; accepted: {s['final_accepted']}; "
                                    f"cited filings: {s.get('cited_doc_kinds')}; evidence: {ev[:300]}")
            self.editor_calls += 1
            try:
                sel, _ = self.editor.json_call(E.EDITOR_SYSTEM, E.select_prompt(q["text"], deliverables),
                                               E.SELECT_SCHEMA, max_tokens=300)
                choice = int(sel.get("choice", 0))
                choice = choice if 0 <= choice < len(composed) else 0
            except ModelUnavailable:
                raise
            except Exception:  # noqa: BLE001
                choice = 0
        h_star, deliverable, info = composed[choice]
        record = {"qid": q["qid"], "k": self.k, "h0": h0.hash, "h_star": h_star.hash,
                  "references": [{"seed": r["seed"], "signals": verifier_free_signals(r)} for r in refs],
                  "candidates": [{"kind": c["kind"], "valid": c["harness"] is not None, "applied": c["applied"],
                                  "rationale": c.get("rationale", ""), "error": c.get("error"),
                                  "contrast": c.get("contrast"),
                                  "signals": verifier_free_signals(c["probe"]) if c.get("probe") else None}
                                 for c in pool],
                  "compose": [x[2] for x in composed], "selected": choice,
                  "cost": {"executor_tokens": self.exec_tokens - exec0, "editor_tokens": self._editor_tokens() - ed0,
                           "editor_calls": self.editor_calls - calls0,
                           "editor_usd": round(float(getattr(self.editor, "usd", 0.0)) - usd0, 5),
                           "editor": getattr(self.editor, "name", "?"),
                           "reference_tokens": sum(r["usage"]["total_tokens"] for r in refs)},
                  "deliverable": {"answer": deliverable["summary"].get("answer"),
                                  "signals": verifier_free_signals(deliverable)}}
        return {"record": record, "deliverable": deliverable, "reference": refs[info["ref_index"]], "h_star": h_star,
                "h0": h0, "applied": info["applied"], "ops": info["ops"], "decision": info["decision"]}

    def update_library(self, q: dict, res: dict) -> dict | None:
        if not self.use_library or res["decision"] == "keep" or not res["applied"]:
            return None
        ok, why = contrast(res["reference"], res["deliverable"])
        if not ok:
            return None
        self.editor_calls += 1
        try:
            les, _ = self.editor.json_call(E.EDITOR_SYSTEM, E.lesson_prompt(
                q["text"], run_digest(res["reference"], q), run_digest(res["deliverable"], q), res["applied"]),
                E.LESSON_SCHEMA, max_tokens=400)
        except ModelUnavailable:
            raise
        except Exception:  # noqa: BLE001
            les = {"situation": ", ".join(tags(q["text"])), "lesson": "; ".join(res["applied"])}
        text = json.dumps(les, ensure_ascii=False)
        if any(name in text for name in self.forbidden):
            les = {"situation": ", ".join(tags(q["text"])), "lesson": "; ".join(res["applied"])}
        entry = {"situation": str(les.get("situation") or ""), "lesson": str(les.get("lesson") or ""),
                 "applied": res["applied"], "ops": res["ops"], "diff": res["h0"].diff(res["h_star"], max_lines=30),
                 "evidence": why, "tags": tags(q["text"]), "task": q["qid"], "support": 1}
        self.library.add(entry)
        return entry

    def stream(self, questions: list[dict], h0: Harness) -> dict:
        self.out.mkdir(parents=True, exist_ok=True)
        results = []
        rec_path = self.out / "records.jsonl"
        done = set()
        if rec_path.exists():
            for line in rec_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    done.add(r["qid"])
                    results.append(r)
        for q in questions:
            if q["qid"] in done:
                continue
            res = self.step(q, h0)
            entry = self.update_library(q, res)
            rec = res["record"]
            rec["library_entry"] = entry["id"] if entry else None
            # scores are attached after the fact, for reporting only
            rec["score_reference"] = res["reference"]["score"]
            rec["score_deliverable"] = res["deliverable"]["score"]
            rec["editor_calls_total"] = self.editor_calls
            with open(rec_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            results.append(rec)
            self.log(f"[harness2] {q['qid']}: decision={res['decision']} applied={res['applied'][:2]} "
                     f"ref={res['reference']['summary']['answer']!r}({'OK' if rec['score_reference']['correct'] else 'x'}) "
                     f"-> {res['deliverable']['summary']['answer']!r}({'OK' if rec['score_deliverable']['correct'] else 'x'})"
                     + (f" +library {entry['id']}" if entry else ""))
        return {"records": results, "library": self.library.entries}

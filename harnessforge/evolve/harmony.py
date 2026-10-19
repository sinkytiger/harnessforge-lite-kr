"""Offline multi-objective harness search (Harmony Harness, arXiv:2610.15150, simplified).

* N weight vectors over (accuracy, cost-efficiency); each subproblem keeps an incumbent harness.
* Weighted Tchebycheff scalarization against the ideal point z*: g(H|λ) = max_j λ_j |z*_j - f_j(H)|.
* Neighbourhood B(i) = the T nearest weight vectors. A child may replace at most `n_r` neighbouring
  incumbents it beats. A stalled subproblem breeds from its best neighbour.
* Factorized variation: a diagnose call picks the component class (tools | skills | logic |
  generalize) and the scope (general | domain); an operator restricted to that slice of the genome
  then writes the edit. A niche lens points each subproblem at its weaker objective, and sibling
  diagnoses from the same generation are shown so subproblems pick different levers.
* Final pick on the search split only: H† = argmax min(f_acc, f_eff). Held-out questions are never
  used for selection.

Deviations from the paper, all for a laptop budget: two objectives are accuracy and token cost
(the paper uses functionality and security), harness edits are declarative files rather than code,
validation is static (schema, bounds, leakage check) instead of a three-stage build, and the
default budget is a few generations with one seed.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..harness import EditError, Harness
from ..harness.genome import SCOPES
from . import editor as E
from .common import flush_print, GuardedLLM, ModelUnavailable, QuotaExhausted, evaluate, failure_digest


@dataclass
class Member:
    harness: Harness
    f: tuple[float, float]           # (accuracy, efficiency)
    metrics: dict
    gen: int
    sub: int | None
    parent: str | None
    diagnosis: dict = field(default_factory=dict)
    ops: list = field(default_factory=list)
    applied: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"hash": self.harness.hash, "f_acc": self.f[0], "f_eff": self.f[1], "gen": self.gen, "sub": self.sub,
                "parent": self.parent, "diagnosis": self.diagnosis, "ops": self.ops, "applied": self.applied,
                "metrics": self.metrics}


def weight_vectors(n: int, lo: float = 0.2, hi: float = 0.8) -> list[tuple[float, float]]:
    if n == 1:
        return [(1.0, 0.0)]
    return [(lo + (hi - lo) * i / (n - 1), 1 - (lo + (hi - lo) * i / (n - 1))) for i in range(n)]


def tchebycheff(f: tuple[float, float], lam: tuple[float, float], z: tuple[float, float]) -> float:
    return max(lam[0] * abs(z[0] - f[0]), lam[1] * abs(z[1] - f[1]))


def neighbourhoods(weights: list[tuple[float, float]], t: int) -> list[list[int]]:
    out = []
    for w in weights:
        d = sorted(range(len(weights)), key=lambda j: math.dist(w, weights[j]))
        out.append(d[:max(1, t)])
    return out


def pareto_front(members: list[Member]) -> list[Member]:
    front = []
    for m in members:
        dominated = any((o.f[0] >= m.f[0] and o.f[1] >= m.f[1]) and (o.f != m.f) for o in members)
        if not dominated and all(o.harness.hash != m.harness.hash for o in front):
            front.append(m)
    return sorted(front, key=lambda m: -m.f[0])


class HarmonySearch:
    def __init__(self, corpus, index, questions: list[dict], client_for_seed, editor_llm, out_dir: Path,
                 n_sub: int = 4, neighbours: int = 2, n_replace: int = 2, generations: int = 3,
                 seeds=(7,), token_cap: int = 80_000, weights: list | None = None, log=flush_print) -> None:
        self.corpus, self.index, self.questions = corpus, index, questions
        self.qmap = {q["qid"]: q for q in questions}
        self.client_for_seed = client_for_seed
        self.editor = GuardedLLM(editor_llm)
        self.out = Path(out_dir)
        self.weights = weights or weight_vectors(n_sub)
        self.B = neighbourhoods(self.weights, neighbours)
        self.n_replace = n_replace
        self.generations = generations
        self.seeds = tuple(seeds)
        self.token_cap = token_cap
        self.log = log
        self.archive: list[Member] = []
        self.z = (0.0, 0.0)
        self.forbidden = sorted({c["name"] for c in corpus.companies})
        self.editor_calls = 0
        self.usd_offset = 0.0

    # ---------------------------------------------------------------- evaluation
    def _eval(self, h: Harness) -> tuple[tuple[float, float], dict, list[dict]]:
        m, trajs = evaluate(self.corpus, self.index, h, self.questions, self.client_for_seed, self.seeds,
                            self.out, token_cap=self.token_cap, log=self.log)
        return (m["accuracy"], m["efficiency"]), m, trajs

    def _update_z(self, f: tuple[float, float]) -> None:
        self.z = (max(self.z[0], f[0]), max(self.z[1], f[1]))

    # ---------------------------------------------------------------- variation
    def _diagnose(self, parent: Member, trajs: list[dict], lam, siblings: list[str]) -> dict:
        lens_acc = lam[0] * abs(self.z[0] - parent.f[0])
        lens_eff = lam[1] * abs(self.z[1] - parent.f[1])
        lens = ("accuracy: make more answers correct" if lens_acc >= lens_eff
                else "cost: reach the same answers with fewer tokens and turns")
        digest = failure_digest(trajs, self.qmap, with_gold=True)
        prompt = E.diagnose_prompt(parent.harness.summary(), digest, lens, lam, siblings)
        self.editor_calls += 1
        d, _ = self.editor.json_call(E.EDITOR_SYSTEM, prompt, E.DIAGNOSE_SCHEMA, max_tokens=500)
        for k in ("diagnosis", "hypothesis"):
            d[k] = str(d.get(k) or "")
        d["component"] = d.get("component") if d.get("component") in ("tools", "skills", "logic", "generalize") else "logic"
        d["scope"] = d.get("scope") if d.get("scope") in SCOPES else "general"
        d["lens"] = lens
        d["digest"] = digest
        return d

    def _operate(self, parent: Member, d: dict) -> tuple[Harness | None, list, list, str | None]:
        component, scope = d["component"], d["scope"]
        root = SCOPES[scope]
        files = {rel: t for rel, t in parent.harness.files.items() if rel.startswith(root + "/")
                 and (component != "tools" or rel.endswith(("tool_guidance.md", "config.json")))
                 and (component != "skills" or "/skills/" in rel)
                 and (component != "logic" or rel.endswith(("system.md", "domain.md", "config.json", "gates.json")))}
        error = None
        ops: list = []
        for attempt in range(2):
            prompt = E.operator_prompt(parent.harness.summary(), d["digest"], d, component, scope, files, error)
            schema = E.op_schema(E.OPS_BY_COMPONENT[component], None if component == "generalize" else scope, component)
            self.editor_calls += 1
            try:
                out, _ = self.editor.json_call(E.EDITOR_SYSTEM, prompt, schema, max_tokens=900)
            except ModelUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - an unusable editor reply skips this child
                error = f"reply was not valid JSON ({exc})"
                continue
            ops = out.get("ops") or []
            try:
                child, applied = parent.harness.apply(ops, component=component,
                                                      scope=None if component == "generalize" else scope,
                                                      forbidden_terms=self.forbidden)
                return child, ops, applied, None
            except EditError as exc:
                error = str(exc)
        return None, ops, [], error

    # ---------------------------------------------------------------- main loop
    def _resume(self, seed_harness: Harness):
        """Rebuild the search state from harmony.json (written after every evaluated child)."""
        st = json.loads((self.out / "harmony.json").read_text(encoding="utf-8"))
        if [tuple(w) for w in st["weights"]] != [tuple(w) for w in self.weights]:
            raise ValueError("harmony.json was written with different weight vectors; use a new --out")
        members: dict[str, Member] = {}
        for m in st["archive"]:
            h = seed_harness if m["gen"] == 0 else Harness.load(self.out / "harnesses" / m["hash"])
            members[m["hash"]] = Member(h, (m["f_acc"], m["f_eff"]), m["metrics"], m["gen"], m["sub"], m["parent"],
                                        m.get("diagnosis") or {}, m.get("ops") or [], m.get("applied") or [])
        self.archive = list(members.values())
        self.z = tuple(st["z"])
        self.editor_calls = st.get("editor_calls", 0)
        self.usd_offset = float((st.get("editor") or {}).get("usd", 0.0))
        incumbents = [members[h] for h in st["incumbents"]]
        history = st["history"]
        last = history[-1] if history else {"gen": 1, "sub": -1}
        start = (last["gen"], last["sub"] + 1) if last["sub"] + 1 < len(self.weights) else (last["gen"] + 1, 0)
        last_state = {e["sub"]: (e["parent"],) for e in history if e["gen"] in (start[0] - 1, start[0])}
        siblings = [f"{e['diagnosis'].get('component')}/{e['diagnosis'].get('scope')}: {e['diagnosis'].get('hypothesis', '')[:120]}"
                    for e in history if e["gen"] == start[0] and e.get("diagnosis")]
        self.log(f"[harmony] resuming at gen {start[0]} sub {start[1]} with {len(self.archive)} evaluated harnesses")
        return incumbents, history, last_state, start, siblings

    def run(self, seed_harness: Harness, resume: bool = True) -> dict:
        self.out.mkdir(parents=True, exist_ok=True)
        self.log(f"[harmony] evaluating seed {seed_harness.hash} on {len(self.questions)} questions x {len(self.seeds)} seeds")
        f, m, trajs0 = self._eval(seed_harness)
        traj_cache = {seed_harness.hash: trajs0}
        start, resumed_siblings = (1, 0), []
        state_file = self.out / "harmony.json"
        if resume and state_file.exists() and json.loads(state_file.read_text(encoding="utf-8")).get("archive"):
            incumbents, history, last_state, start, resumed_siblings = self._resume(seed_harness)
            seed_member = self.archive[0]
        else:
            seed_member = Member(seed_harness, f, m, 0, None, None)
            self.archive.append(seed_member)
            self._update_z(f)
            incumbents = [seed_member for _ in self.weights]
            last_state: dict[int, tuple] = {}
            history = []
        for gen in range(start[0], self.generations + 1):
            siblings: list[str] = list(resumed_siblings) if gen == start[0] else []
            for i, lam in enumerate(self.weights):
                if (gen, i) < start:
                    continue
                parent = incumbents[i]
                state = (parent.harness.hash,)
                if last_state.get(i) == state:
                    best = min(self.B[i], key=lambda j: tchebycheff(incumbents[j].f, lam, self.z))
                    if incumbents[best].harness.hash != parent.harness.hash:
                        self.log(f"[harmony] gen {gen} sub {i}: stalled, breeding from neighbour {best}")
                        parent = incumbents[best]
                last_state[i] = state
                trajs = traj_cache.get(parent.harness.hash)
                if trajs is None:
                    _, _, trajs = self._eval(parent.harness)
                    traj_cache[parent.harness.hash] = trajs
                try:
                    d = self._diagnose(parent, trajs, lam, siblings)
                except ModelUnavailable:
                    raise
                except Exception as exc:  # noqa: BLE001 - an unusable editor reply skips this subproblem
                    self.log(f"[harmony] gen {gen} sub {i}: diagnose failed ({exc}); skipped")
                    history.append({"gen": gen, "sub": i, "weights": lam, "parent": parent.harness.hash,
                                    "error": f"diagnose failed: {exc}"[:200]})
                    continue
                siblings.append(f"{d['component']}/{d['scope']}: {d.get('hypothesis', '')[:120]}")
                self.log(f"[harmony] gen {gen} sub {i} λ=({lam[0]:.2f},{lam[1]:.2f}) {d['lens'].split(':')[0]} -> "
                         f"{d['component']}/{d['scope']}: {d.get('hypothesis', '')[:100]}")
                child_h, ops, applied, err = self._operate(parent, d)
                rec = {"gen": gen, "sub": i, "weights": lam, "parent": parent.harness.hash,
                       "diagnosis": {k: v for k, v in d.items() if k != "digest"}, "ops": ops, "applied": applied,
                       "error": err}
                if child_h is None:
                    self.log(f"[harmony]   edit rejected: {err}")
                    history.append(rec)
                    continue
                self.log(f"[harmony]   child {child_h.hash}: {'; '.join(applied)}")
                cf, cm, ctrajs = self._eval(child_h)
                traj_cache[child_h.hash] = ctrajs
                child = Member(child_h, cf, cm, gen, i, parent.harness.hash,
                               {k: v for k, v in d.items() if k != "digest"}, ops, applied)
                self.archive.append(child)
                self._update_z(cf)
                replaced = []
                for j in self.B[i]:
                    if len(replaced) >= self.n_replace:
                        break
                    if tchebycheff(cf, self.weights[j], self.z) < tchebycheff(incumbents[j].f, self.weights[j], self.z):
                        incumbents[j] = child
                        replaced.append(j)
                rec.update({"child": child_h.hash, "f": cf, "replaced": replaced})
                history.append(rec)
                self.log(f"[harmony]   f=(acc {cf[0]:.3f}, eff {cf[1]:.3f}) z*=({self.z[0]:.3f},{self.z[1]:.3f}) replaced {replaced}")
                child_h.save(self.out / "harnesses" / child_h.hash)
                self._checkpoint(history, incumbents)
        best = max(self.archive, key=lambda mem: (min(mem.f), -mem.gen))
        if (self.out / "best").exists():
            shutil.rmtree(self.out / "best")
        best.harness.save(self.out / "best")
        result = self._checkpoint(history, incumbents, best)
        self.log(f"[harmony] best {best.harness.hash} f=(acc {best.f[0]:.3f}, eff {best.f[1]:.3f}); "
                 f"seed f=(acc {seed_member.f[0]:.3f}, eff {seed_member.f[1]:.3f}); editor calls {self.editor_calls}")
        return result

    def _checkpoint(self, history, incumbents, best: Member | None = None) -> dict:
        front = pareto_front(self.archive)
        result = {"weights": self.weights, "z": self.z, "archive": [m.to_json() for m in self.archive],
                  "front": [m.harness.hash for m in front], "incumbents": [m.harness.hash for m in incumbents],
                  "history": history, "best": best.harness.hash if best else None, "editor_calls": self.editor_calls,
                  "editor": {"name": getattr(self.editor, "name", "?"), "usd": round(self.usd_offset + float(getattr(self.editor, "usd", 0.0)), 4),
                             "usage": self.editor.usage.to_json() if hasattr(self.editor, "usage") else {}}}
        (self.out / "harmony.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return result

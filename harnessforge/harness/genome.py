"""The harness genome: what evolution is allowed to change.

Following Harness^2 and Harmony Harness, a harness is a set of files around a frozen model. Here
they are declarative, so a small editor model cannot break the runtime:

    general/system.md          loop instructions (logic)
    general/tool_guidance.md   how to call the tools (tools)
    general/config.json        knobs with bounds
    general/gates.json         general verification gates
    general/skills/*.md        skills with a `when` trigger (skills)
    domain/dart/domain.md      domain notes (logic)
    domain/dart/tool_guidance.md
    domain/dart/config.json    overrides of the general knobs
    domain/dart/gates.json     domain gates (correction_check, preliminary_check, unit_declared)
    domain/dart/skills/*.md

The split into ``general`` and ``domain`` scopes is Harmony Harness's factorization; it is also the
invariant / domain-specific split of Harness^2's two proposal editors. The tools themselves, the
scoring and the corpus are frozen: they are the evaluator interface.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..runtime.env import DOMAIN_GATES, GENERAL_GATES

SCOPES = {"general": "general", "domain": "domain/dart"}
CONFIG_BOUNDS = {
    "max_turns": (6, 30),
    "search_k": (2, 8),
    "snippet_chars": (80, 300),
    "read_chars": (400, 2400),
    "history_window": (1, 8),
    "max_skills": (0, 6),
    "thought_chars": (60, 600),
}
FROZEN_CONFIG = {"state_mode"}
TOOL_KNOBS = {"search_k", "snippet_chars", "read_chars"}
LOGIC_KNOBS = {"max_turns", "history_window", "max_skills", "thought_chars"}
COMPONENTS = ("tools", "skills", "logic")
MAX_FILE_CHARS = 2400
MAX_SKILL_CHARS = 900
MAX_SKILLS_PER_SCOPE = 8
MAX_SYSTEM_CHARS = 7000
SEED_DIR = Path(__file__).resolve().parent.parent / "harness_seed"


class EditError(ValueError):
    pass


@dataclass
class Skill:
    name: str
    scope: str
    when: list[str]
    summary: str
    body: str

    def render(self) -> str:
        head = "---\n" + f"name: {self.name}\nwhen: {', '.join(self.when)}\nsummary: {self.summary}\n---\n"
        return head + self.body.strip() + "\n"


def parse_skill(text: str, scope: str, fallback_name: str) -> Skill:
    meta: dict[str, str] = {}
    body = text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    when = [w.strip() for w in meta.get("when", "*").split(",") if w.strip()] or ["*"]
    return Skill(meta.get("name", fallback_name), scope, when, meta.get("summary", ""), body.strip())


@dataclass
class Harness:
    files: dict[str, str] = field(default_factory=dict)
    label: str = ""

    # -------------------------------------------------------------- io
    @classmethod
    def load(cls, path: str | Path, label: str = "") -> "Harness":
        path = Path(path)
        files = {}
        for p in sorted(path.rglob("*")):
            if p.is_file() and p.suffix in (".md", ".json"):
                files[p.relative_to(path).as_posix()] = p.read_text(encoding="utf-8")
        if not files:
            raise FileNotFoundError(f"no harness files under {path}")
        return cls(files, label or path.name)

    @classmethod
    def seed(cls, variant: str = "longharness") -> "Harness":
        return cls.load(SEED_DIR / variant, label=f"seed-{variant}")

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        for rel, text in self.files.items():
            p = path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return path

    def copy(self, label: str | None = None) -> "Harness":
        return Harness(copy.deepcopy(self.files), self.label if label is None else label)

    @property
    def hash(self) -> str:
        blob = json.dumps(self.files, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:12]

    # -------------------------------------------------------------- accessors
    def _json(self, rel: str) -> dict:
        return json.loads(self.files.get(rel, "{}") or "{}")

    def config(self, scopes: tuple[str, ...] = ("general", "domain")) -> dict:
        cfg = self._json("general/config.json")
        if "domain" in scopes:
            cfg.update(self._json("domain/dart/config.json"))
        return cfg

    def gates(self, scopes: tuple[str, ...] = ("general", "domain")) -> dict:
        g = dict(GENERAL_GATES)
        g.update({k: v for k, v in self._json("general/gates.json").items() if k in GENERAL_GATES})
        if "domain" in scopes:
            g.update(DOMAIN_GATES)
            g.update({k: v for k, v in self._json("domain/dart/gates.json").items() if k in DOMAIN_GATES})
        return g

    def text(self, rel: str) -> str:
        return self.files.get(rel, "")

    def skills(self, scope: str | None = None) -> list[Skill]:
        out = []
        for sc, root in SCOPES.items():
            if scope and sc != scope:
                continue
            prefix = f"{root}/skills/"
            for rel in sorted(self.files):
                if rel.startswith(prefix) and rel.endswith(".md"):
                    out.append(parse_skill(self.files[rel], sc, rel[len(prefix):-3]))
        return out

    def summary(self, max_chars: int = 400) -> str:
        """Compact description for editor prompts."""
        lines = [f"harness {self.hash}"]
        for rel in sorted(self.files):
            if rel.endswith(".json"):
                lines.append(f"- {rel}: {json.dumps(self._json(rel), ensure_ascii=False)}")
        for rel in ("general/system.md", "general/tool_guidance.md", "domain/dart/domain.md", "domain/dart/tool_guidance.md"):
            if rel in self.files:
                t = self.files[rel].strip().replace("\n", " / ")
                lines.append(f"- {rel} ({len(self.files[rel])} chars): {t[:max_chars]}{'...' if len(t) > max_chars else ''}")
        for sk in self.skills():
            lines.append(f"- skill [{sk.scope}] {sk.name} (when: {', '.join(sk.when)}): {sk.summary or sk.body[:80]}")
        return "\n".join(lines)

    def diff(self, other: "Harness", max_lines: int = 40) -> str:
        out: list[str] = []
        for rel in sorted(set(self.files) | set(other.files)):
            a, b = self.files.get(rel, ""), other.files.get(rel, "")
            if a != b:
                out += list(difflib.unified_diff(a.splitlines(), b.splitlines(), f"a/{rel}", f"b/{rel}", lineterm="", n=0))
        if len(out) > max_lines:
            out = out[:max_lines] + [f"... ({len(out) - max_lines} more diff lines)"]
        return "\n".join(out) or "(no change)"

    # -------------------------------------------------------------- validation
    def validate(self, forbidden_terms: list[str] = ()) -> list[str]:
        errs = []
        for rel, text in self.files.items():
            limit = MAX_SKILL_CHARS + 200 if "/skills/" in rel else MAX_FILE_CHARS
            if len(text) > limit:
                errs.append(f"{rel} is {len(text)} chars (limit {limit})")
            for term in forbidden_terms:
                if term and term in text:
                    errs.append(f"{rel} mentions '{term}': harness text must not contain corpus-specific facts")
            if re.search(r"\d{1,3}(,\d{3}){2,}", text):
                errs.append(f"{rel} contains a large specific figure; harness text must not memorise numbers")
            if rel.endswith(".json"):
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    errs.append(f"{rel} is not valid JSON: {exc}")
        for scope in SCOPES:
            cfg = self._json(f"{SCOPES[scope]}/config.json") if f"{SCOPES[scope]}/config.json" in self.files else {}
            for k, v in cfg.items():
                if k in FROZEN_CONFIG:
                    continue
                if k not in CONFIG_BOUNDS:
                    errs.append(f"unknown config key {k}")
                    continue
                lo, hi = CONFIG_BOUNDS[k]
                if not isinstance(v, int) or not lo <= v <= hi:
                    errs.append(f"config {k}={v!r} outside [{lo}, {hi}]")
            if len(self.skills(scope)) > MAX_SKILLS_PER_SCOPE:
                errs.append(f"too many skills in {scope}")
        if self.config().get("state_mode") not in ("longharness", "notes"):
            errs.append("state_mode must be longharness or notes")
        return errs

    # -------------------------------------------------------------- edits
    def apply(self, ops: list[dict], component: str | None = None, scope: str | None = None,
              forbidden_terms: list[str] = ()) -> tuple["Harness", list[str]]:
        """Apply edit operations; `component`/`scope` restrict which operations are legal (Harmony's
        factorized operators). Returns the child harness and a description of each applied op."""
        child = self.copy()
        done: list[str] = []
        if not isinstance(ops, list) or not ops:
            raise EditError("no operations")
        for op in ops[:6]:
            if not isinstance(op, dict):
                raise EditError(f"each operation must be a JSON object, got {type(op).__name__}")
            try:
                done.append(child._apply_one(op, component, scope))
            except EditError:
                raise
            except (AttributeError, TypeError, ValueError, OverflowError, KeyError) as exc:
                raise EditError(f"malformed operation {op.get('op')!r}: {exc}") from exc
        errs = child.validate(forbidden_terms)
        if errs:
            raise EditError("; ".join(errs[:4]))
        if child.hash == self.hash:
            raise EditError("the operations did not change the harness")
        return child, done

    def _apply_one(self, op: dict, component: str | None, scope: str | None) -> str:
        kind = str(op.get("op", "")).strip()
        sc = str(op.get("scope") or scope or "general").strip()
        if sc not in SCOPES:
            raise EditError(f"unknown scope {sc}")
        if kind == "move_skill" and component != "generalize":
            raise EditError("move_skill is only available to the generalize operator")
        if scope and sc != scope and kind != "move_skill":
            raise EditError(f"this operator may only edit the {scope} scope")
        root = SCOPES[sc]
        allowed = {
            "tools": {"append_text", "replace_text", "set_config"},
            "skills": {"write_skill", "delete_skill"},
            "logic": {"append_text", "replace_text", "set_config", "set_gate"},
            "generalize": {"move_skill"},
        }
        if component and kind not in allowed.get(component, set()):
            raise EditError(f"op '{kind}' is not allowed for component '{component}'")
        if kind in ("append_text", "replace_text"):
            fname = str(op.get("file") or "").strip()
            legal = {"tools": {"tool_guidance.md"},
                     "logic": {"system.md"} if sc == "general" else {"domain.md"}}
            if component in legal and fname not in legal[component]:
                raise EditError(f"component '{component}' may edit only {sorted(legal[component])} in {sc}")
            if fname not in ("system.md", "tool_guidance.md", "domain.md"):
                raise EditError(f"unknown file {fname}")
            if fname == "system.md" and sc != "general" or fname == "domain.md" and sc != "domain":
                raise EditError(f"{fname} does not exist in scope {sc}")
            rel = f"{root}/{fname}"
            cur = self.files.get(rel, "")
            if kind == "append_text":
                add = str(op.get("content") or "").strip()
                if not add:
                    raise EditError("append_text needs content")
                self.files[rel] = (cur.rstrip() + "\n" + add + "\n").lstrip()
                return f"append {len(add)} chars to {rel}"
            old, new = str(op.get("old") or ""), str(op.get("new") or "")
            if not old or old not in cur:
                raise EditError(f"replace_text: 'old' text not found in {rel}")
            self.files[rel] = cur.replace(old, new, 1)
            return f"replace text in {rel}"
        if kind == "set_config":
            key = str(op.get("key") or "").strip()
            if key in FROZEN_CONFIG or key not in CONFIG_BOUNDS:
                raise EditError(f"config key {key!r} cannot be set")
            if component == "tools" and key not in TOOL_KNOBS or component == "logic" and key not in LOGIC_KNOBS:
                raise EditError(f"component '{component}' cannot set {key}")
            try:
                value = int(float(str(op.get("value")).strip()))
            except (TypeError, ValueError) as exc:
                raise EditError(f"set_config value must be a number, got {op.get('value')!r}") from exc
            lo, hi = CONFIG_BOUNDS[key]
            value = max(lo, min(hi, value))
            rel = f"{root}/config.json"
            cfg = self._json(rel) if rel in self.files else {}
            cfg[key] = value
            self.files[rel] = json.dumps(cfg, ensure_ascii=False, indent=1)
            return f"set {sc} config {key}={value}"
        if kind == "set_gate":
            key = str(op.get("key") or "").strip()
            pool = GENERAL_GATES if sc == "general" else DOMAIN_GATES
            if key not in pool:
                raise EditError(f"gate {key!r} does not exist in scope {sc} (have {sorted(pool)})")
            value = str(op.get("value")).strip().lower() in ("true", "1", "yes", "on")
            rel = f"{root}/gates.json"
            g = self._json(rel) if rel in self.files else {}
            g[key] = value
            self.files[rel] = json.dumps(g, ensure_ascii=False, indent=1)
            return f"set {sc} gate {key}={value}"
        if kind == "write_skill":
            name = re.sub(r"[^a-z0-9_]+", "_", str(op.get("name") or "").strip().lower()).strip("_")[:40]
            body = str(op.get("content") or "").strip()
            if not name or not body:
                raise EditError("write_skill needs name and content")
            if len(body) > MAX_SKILL_CHARS:
                raise EditError(f"skill body is {len(body)} chars (limit {MAX_SKILL_CHARS})")
            when = op.get("when") or ["*"]
            if not isinstance(when, (str, list, tuple)):
                when = [str(when)]
            if isinstance(when, str):
                when = [w.strip() for w in when.split(",")]
            when = [str(w).strip()[:20] for w in when if str(w).strip()][:6] or ["*"]
            sk = Skill(name, sc, when, str(op.get("summary") or "").strip()[:120], body)
            self.files[f"{root}/skills/{name}.md"] = sk.render()
            return f"write skill {sc}/{name} (when: {', '.join(when)})"
        if kind == "delete_skill":
            name = str(op.get("name") or "").strip()
            rel = f"{root}/skills/{name}.md"
            if rel not in self.files:
                raise EditError(f"no skill {name} in {sc}")
            del self.files[rel]
            return f"delete skill {sc}/{name}"
        if kind == "move_skill":
            name = str(op.get("name") or "").strip()
            to = str(op.get("to") or "").strip()
            if to not in SCOPES:
                raise EditError("move_skill needs to: general|domain")
            src = [s for s in SCOPES if s != to][0]
            rel = f"{SCOPES[src]}/skills/{name}.md"
            if rel not in self.files:
                raise EditError(f"no skill {name} in {src}")
            self.files[f"{SCOPES[to]}/skills/{name}.md"] = self.files.pop(rel)
            return f"move skill {name}: {src} -> {to}"
        raise EditError(f"unknown op '{kind}'")

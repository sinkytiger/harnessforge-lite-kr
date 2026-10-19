"""Dynamic composition at inference time (Harmony Harness, Section 5, simplified).

For each task the composer selects which skills from the general pool and the domain pool are
loaded, and which gates apply. The components themselves are never modified here. In transfer
mode only general components are loaded, which keeps domain-specific fixes from leaking into a
new domain.

Two routers:
* ``keyword`` (default, free, deterministic): a skill is loaded when one of its `when` keywords
  occurs in the question, or when its trigger is "*".
* ``llm``: the model picks skills by name from their one-line summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .genome import Harness, Skill


@dataclass
class Instance:
    harness_hash: str
    system: str
    config: dict
    gates: dict
    skills: list[str] = field(default_factory=list)
    scopes: tuple[str, ...] = ("general", "domain")

    @property
    def mode(self) -> str:
        return self.config.get("state_mode", "longharness")


def _keyword_pick(skills: list[Skill], question: str, limit: int) -> list[Skill]:
    always = [s for s in skills if "*" in s.when]
    matched = [s for s in skills if "*" not in s.when and any(w and w in question for w in s.when)]
    return (always + matched)[:limit]


def compose(harness: Harness, question: str, scopes: tuple[str, ...] = ("general", "domain"),
            router: str = "keyword", llm=None) -> Instance:
    cfg = harness.config(scopes)
    gates = harness.gates(scopes)
    limit = int(cfg.get("max_skills", 4))
    pool = [s for s in harness.skills() if s.scope in scopes]
    if router == "llm" and llm is not None and pool:
        chosen = _llm_pick(llm, pool, question, limit)
    else:
        chosen = _keyword_pick(pool, question, limit)
    parts = [harness.text("general/system.md").strip()]
    tg = harness.text("general/tool_guidance.md").strip()
    if "domain" in scopes:
        tg = (tg + "\n" + harness.text("domain/dart/tool_guidance.md").strip()).strip()
    if tg:
        parts.append("## Tool guidance\n" + tg)
    if "domain" in scopes and harness.text("domain/dart/domain.md").strip():
        parts.append("## Domain notes\n" + harness.text("domain/dart/domain.md").strip())
    if chosen:
        parts.append("## Skills\n" + "\n\n".join(f"### {s.name}\n{s.body}" for s in chosen))
    return Instance(harness.hash, "\n\n".join(p for p in parts if p), cfg, gates,
                    [f"{s.scope}/{s.name}" for s in chosen], scopes)


def _llm_pick(llm, pool: list[Skill], question: str, limit: int) -> list[Skill]:
    menu = "\n".join(f"- {s.name}: {s.summary or s.body[:100]}" for s in pool)
    schema = {"type": "object", "properties": {"skills": {"type": "array", "items": {"type": "string"}}},
              "required": ["skills"]}
    try:
        out, _ = llm.json_call("You choose which skills help answer a research question. Reply in JSON.",
                               f"Question: {question}\n\nSkills:\n{menu}\n\nPick at most {limit} skill names.",
                               schema, max_tokens=200)
        names = [str(n) for n in out.get("skills", [])]
    except Exception:  # noqa: BLE001 - the router must never break an episode
        return _keyword_pick(pool, question, limit)
    picked = [s for s in pool if s.name in names][:limit]
    always = [s for s in pool if "*" in s.when and s not in picked]
    return (always + picked)[:limit]

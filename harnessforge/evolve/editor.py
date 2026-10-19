"""Editor prompts and JSON schemas.

The editor is an LLM that reads execution evidence and writes harness edits as JSON operations,
which the genome validates and applies. Edits are small and declarative, so even a small local
model can act as editor; a stronger editor model can be plugged in with --editor-model.
"""

from __future__ import annotations

import json

from ..harness.genome import CONFIG_BOUNDS, LOGIC_KNOBS, TOOL_KNOBS
from ..runtime.env import DOMAIN_GATES, GENERAL_GATES

OPS_BY_COMPONENT = {
    "tools": ["append_text", "replace_text", "set_config"],
    "skills": ["write_skill", "delete_skill"],
    "logic": ["append_text", "replace_text", "set_config", "set_gate"],
    "generalize": ["move_skill"],
    "any": ["append_text", "replace_text", "set_config", "set_gate", "write_skill", "delete_skill"],
}


def op_schema(ops: list[str], scope: str | None, component: str | None = None) -> dict:
    """One schema variant per operation, each with its own required fields (anyOf).

    A single flat object with every field optional let models omit the field that matters
    (e.g. a write_skill without `content`). Variants make each operation complete by construction.
    """
    scopes = [scope] if scope else ["general", "domain"]
    files = {"general": ["system.md", "tool_guidance.md"], "domain": ["domain.md", "tool_guidance.md"]}
    knobs = sorted(TOOL_KNOBS if component == "tools" else LOGIC_KNOBS if component == "logic" else TOOL_KNOBS | LOGIC_KNOBS)
    gates = sorted((GENERAL_GATES if "general" in scopes else {}) | (DOMAIN_GATES if "domain" in scopes else {}))
    file_enum = sorted({f for s in scopes for f in files[s]})

    def obj(name: str, props: dict) -> dict:
        p = {"op": {"type": "string", "enum": [name]}, "scope": {"type": "string", "enum": scopes}} | props
        return {"type": "object", "properties": p, "required": list(p)}

    text = {"type": "string", "maxLength": 800}
    variants = {
        "append_text": obj("append_text", {"file": {"type": "string", "enum": file_enum}, "content": text}),
        "replace_text": obj("replace_text", {"file": {"type": "string", "enum": file_enum},
                                             "old": {"type": "string", "maxLength": 300},
                                             "new": {"type": "string", "maxLength": 600}}),
        "set_config": obj("set_config", {"key": {"type": "string", "enum": knobs}, "value": {"type": "string"}}),
        "set_gate": obj("set_gate", {"key": {"type": "string", "enum": gates}, "value": {"type": "string", "enum": ["true", "false"]}}),
        "write_skill": obj("write_skill", {"name": {"type": "string"}, "when": {"type": "array", "items": {"type": "string"}},
                                           "summary": {"type": "string", "maxLength": 120}, "content": text}),
        "delete_skill": obj("delete_skill", {"name": {"type": "string"}}),
        "move_skill": obj("move_skill", {"name": {"type": "string"}, "to": {"type": "string", "enum": ["general", "domain"]}}),
    }
    items = [variants[o] for o in ops if o in variants]
    item = items[0] if len(items) == 1 else {"anyOf": items}
    return {"type": "object", "properties": {"rationale": {"type": "string", "maxLength": 300},
                                             "ops": {"type": "array", "items": item}},
            "required": ["rationale", "ops"]}


DIAGNOSE_SCHEMA = {"type": "object", "properties": {
    "diagnosis": {"type": "string", "maxLength": 300},
    "hypothesis": {"type": "string", "maxLength": 300},
    "component": {"type": "string", "enum": ["tools", "skills", "logic", "generalize"]},
    "scope": {"type": "string", "enum": ["general", "domain"]}},
    "required": ["diagnosis", "hypothesis", "component", "scope"]}

COMPOSE_SCHEMA = {"type": "object", "properties": {
    "rationale": {"type": "string", "maxLength": 400},
    "decision": {"type": "string", "enum": ["keep", "adopt_invariant", "adopt_domain", "merge"]}},
    "required": ["rationale", "decision"]}

SELECT_SCHEMA = {"type": "object", "properties": {
    "rationale": {"type": "string", "maxLength": 300}, "choice": {"type": "integer"}},
    "required": ["rationale", "choice"]}

LESSON_SCHEMA = {"type": "object", "properties": {
    "situation": {"type": "string", "maxLength": 200},
    "lesson": {"type": "string", "maxLength": 400}},
    "required": ["situation", "lesson"]}


def harness_reference() -> str:
    tk = ", ".join(f"{k} {CONFIG_BOUNDS[k]}" for k in sorted(TOOL_KNOBS))
    lk = ", ".join(f"{k} {CONFIG_BOUNDS[k]}" for k in sorted(LOGIC_KNOBS))
    return f"""HARNESS COMPONENTS (files around a frozen research agent; tools and scoring are fixed):
- scope "general" = mechanisms useful in any document-research task; scope "domain" = Korean DART filings knowledge.
- tools: tool_guidance.md text; knobs {tk}
- skills: short instruction files loaded when a keyword in "when" appears in the question ("*" = always)
- logic: system.md (general) / domain.md (domain) text; knobs {lk}; gates general {sorted(GENERAL_GATES)}, domain {sorted(DOMAIN_GATES)}
EDIT OPERATIONS (JSON):
- {{"op":"append_text","scope":"general","file":"system.md","content":"..."}} (file: system.md | tool_guidance.md | domain.md)
- {{"op":"replace_text","scope":"general","file":"tool_guidance.md","old":"exact old text","new":"new text"}}
- {{"op":"set_config","scope":"general","key":"read_chars","value":"1800"}}
- {{"op":"set_gate","scope":"domain","key":"correction_check","value":"true"}}
- {{"op":"write_skill","scope":"domain","name":"snake_case_name","when":["키워드"],"summary":"one line","content":"instructions"}}
- {{"op":"delete_skill","scope":"general","name":"..."}} ; {{"op":"move_skill","scope":"general","name":"...","to":"domain"}}
RULES: never write company names or specific figures from the corpus into the harness; keep each text short and imperative; one to three operations."""


EDITOR_SYSTEM = ("You improve the harness of a small research agent. You read evidence from its runs and propose "
                 "precise, minimal edits as JSON. Fix the cause of the observed problem, not its symptom.")


def diagnose_prompt(harness_summary: str, digest: str, lens: str, weights: tuple, siblings: list[str]) -> str:
    sib = "\n".join(f"- {s}" for s in siblings) or "- (none yet)"
    return f"""{harness_reference()}

CURRENT HARNESS
{harness_summary}

EXECUTION FEEDBACK ON THE SEARCH SPLIT (gold answers are shown for this split)
{digest[:5000]}

This subproblem weights accuracy {weights[0]:.2f} and cost-efficiency {weights[1]:.2f}. Focus: {lens}.
Other subproblems this generation already target (pick a different lever):
{sib}

Diagnose the main cause of failure, state one hypothesis for a fix, and choose the component
(tools | skills | logic | generalize) and the scope (general | domain) to edit. Reply in JSON."""


def operator_prompt(harness_summary: str, digest: str, diagnosis: dict, component: str, scope: str,
                    files: dict[str, str], error: str | None = None) -> str:
    shown = "\n".join(f"--- {rel}\n{text.strip()[:1200]}" for rel, text in files.items())
    err = f"\nYOUR PREVIOUS EDIT WAS REJECTED: {error}\nFix it.\n" if error else ""
    return f"""{harness_reference()}

CURRENT HARNESS
{harness_summary}

FILES YOU MAY EDIT ({component}, scope {scope})
{shown or '(none yet; you may create skills)'}

FEEDBACK
{digest[:2500]}

DIAGNOSIS: {diagnosis.get('diagnosis')}
HYPOTHESIS: {diagnosis.get('hypothesis')}
{err}
Write 1-3 operations of component '{component}' in scope '{scope}' that implement the hypothesis. Reply in JSON."""


def propose_prompt(kind: str, question: str, harness_summary: str, ref_digest: str, library: list[dict]) -> str:
    focus = ("INVARIANT weaknesses that would recur in any long-document research task: planning, tool use, "
             "reading, evidence discipline, context and budget management. Edit scope 'general' only."
             if kind == "invariant" else
             "DOMAIN-SPECIFIC knowledge, procedures and constraints for Korean DART filings (report types, "
             "corrections, preliminary figures, units, statement bases, period columns). Edit scope 'domain' only.")
    lib = "\n".join(f"- [{e['id']}] situation: {e['situation']} | lesson: {e['lesson']} | ops: "
                    f"{json.dumps(e['ops'], ensure_ascii=False)[:300]}" for e in library) or "- (empty)"
    return f"""{harness_reference()}

TASK (no answer key is available; judge only from the run itself)
{question}

CURRENT HARNESS
{harness_summary}

REFERENCE RUN OF THE CURRENT HARNESS ON THIS TASK
{ref_digest}

EXPERIENCE LIBRARY (lessons from earlier tasks; reuse or adapt only if they fit this run)
{lib}

Propose an edit that targets {focus}
Task-specific facts must come from this task's evidence and must not be written into the harness. Reply in JSON."""


def compose_prompt(question: str, ref_digest: str, candidates: list[dict]) -> str:
    blocks = []
    for c in candidates:
        if c.get("harness") is None:
            blocks.append(f"CANDIDATE {c['kind'].upper()}: invalid edit ({c.get('error')}); not probed")
            continue
        blocks.append(f"CANDIDATE {c['kind'].upper()}\nedit: {c['rationale']}\ndiff:\n{c['diff']}\nprobe run:\n{c['digest']}")
    return f"""You decide which harness edits to keep for this task. There is NO answer key: judge by behavioural
contrast. An edit is supported when its probe run fixes a deficiency visible in the reference run
(no accepted final, gate rejections, invalid actions, repeated searches, values not found in the cited source,
citing an outdated or preliminary filing) without introducing a new one. Two runs that agree on the answer
with clean evidence are more trustworthy than one.

TASK
{question}

REFERENCE RUN (current harness)
{ref_digest}

{chr(10).join(blocks)}

Decide: keep (no edit is supported), adopt_invariant, adopt_domain, or merge (both are supported and compatible). Reply in JSON."""


def select_prompt(question: str, deliverables: list[str]) -> str:
    opts = "\n\n".join(f"OPTION {i}\n{d}" for i, d in enumerate(deliverables))
    return f"""Several anonymous runs answered the same task. Choose the answer best supported by its cited evidence
and the task's requirements (unit, period, statement basis, final/corrected figures). No answer key exists.

TASK
{question}

{opts}

Reply in JSON with the option number."""


def lesson_prompt(question: str, before: str, after: str, ops_desc: list[str]) -> str:
    return f"""An edit to an agent harness changed its behaviour on a task. Write a reusable lesson.

TASK: {question}
BEFORE (reference run):
{before}
EDIT: {'; '.join(ops_desc)}
AFTER (composed run):
{after}

Describe the situation in which this edit helps (no company names or figures) and the lesson in one or two sentences. Reply in JSON."""

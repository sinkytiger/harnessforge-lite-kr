"""Explicit agent state, following LongHarness (arXiv:2610.13075).

* SourceRegistry: every ``read`` registers a span id (S1, S2, ...) mapped to document offsets.
  A statement may cite only spans registered by an earlier read.
* EvidenceBank: atomic, source-linked statements with an immutable id (E1, E2, ...) and a
  lifecycle status: candidate -> active, and active -> superseded (revised with a replacement) or
  retracted (revised to nothing). Only active entries can be cited by ``compute`` and ``final``.
* ConclusionState: established claims, supported hypotheses and unresolved gaps. The gap list is
  the agenda that steers the next search.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STATUSES = ("candidate", "active", "superseded", "retracted")


@dataclass
class Span:
    sid: str
    doc_id: str
    start: int
    end: int
    turn: int


@dataclass
class Evidence:
    eid: str
    text: str
    refs: list[str]
    value: float | None
    unit: str | None
    status: str
    turn: int
    replaces: str | None = None
    replaced_by: str | None = None
    value_found: bool | None = None   # did the value appear in the cited span text (computed always)

    def brief(self) -> str:
        v = "" if self.value is None else f" = {self.value:,.6g}{' ' + self.unit if self.unit else ''}"
        return f"{self.eid} [{','.join(self.refs)}] {self.text}{v}"


class SourceRegistry:
    def __init__(self) -> None:
        self.spans: dict[str, Span] = {}

    def register(self, doc_id: str, start: int, end: int, turn: int) -> Span:
        sid = f"S{len(self.spans) + 1}"
        span = Span(sid, doc_id, start, end, turn)
        self.spans[sid] = span
        return span


class EvidenceBank:
    def __init__(self) -> None:
        self.entries: dict[str, Evidence] = {}
        self.log: list[str] = []

    def _next_id(self) -> str:
        return f"E{len(self.entries) + 1}"

    def admit(self, text: str, refs: list[str], value: float | None, unit: str | None, turn: int,
              value_found: bool | None, replaces: str | None = None) -> Evidence:
        ev = Evidence(self._next_id(), text, list(refs), value, unit, "active", turn, replaces=replaces,
                      value_found=value_found)
        self.entries[ev.eid] = ev
        self.log.append(f"T{turn} admit {ev.eid}")
        return ev

    def revise(self, eid: str, replacement: Evidence | None, turn: int) -> None:
        old = self.entries[eid]
        if replacement is None:
            old.status = "retracted"
            self.log.append(f"T{turn} retract {eid}")
        else:
            old.status = "superseded"
            old.replaced_by = replacement.eid
            self.log.append(f"T{turn} supersede {eid} -> {replacement.eid}")

    def active(self) -> list[Evidence]:
        return [e for e in self.entries.values() if e.status == "active"]

    def inactive(self) -> list[Evidence]:
        return [e for e in self.entries.values() if e.status in ("superseded", "retracted")]


@dataclass
class ConclusionState:
    established: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def update(self, payload: dict) -> bool:
        """Replace the lists the policy sent. An omitted or empty list keeps its value; ["none"] clears it."""
        changed = False
        for name in ("established", "hypotheses", "unresolved"):
            items = payload.get(name)
            if not isinstance(items, list) or not items:
                continue
            items = [str(x).strip()[:200] for x in items if str(x).strip()][:8]
            if len(items) == 1 and items[0].lower() in ("none", "-", "없음"):
                items = []
            if items != getattr(self, name):
                setattr(self, name, items)
                changed = True
        return changed

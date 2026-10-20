"""Answer parsing, scoring against gold, and trap attribution (used only after an episode ends)."""

from __future__ import annotations

import re

_NUM = re.compile(r"[-−△]?\s*\d[\d,]*(?:\.\d+)?")
_ABSTAIN = re.compile(r"알\s*수\s*없|확인할\s*수\s*없|확인\s*불가|공시되지\s*않|해당\s*없|^\s*없음\s*$|unknown|not\s+disclosed|^\s*n/?a\s*$", re.I)


def is_abstain(answer) -> bool:
    return isinstance(answer, str) and bool(_ABSTAIN.search(answer))


# Years, fiscal periods and quarter labels are not the answer ("2025년 12.34" -> 12.34).
_PERIOD = re.compile(r"(?:19|20)\d{2}\s*(?:년|사업연도|회계연도)|제\s*\d+\s*기|\d\s*분기|\d+\s*개월|\bFY\s*\d{2,4}")
_JO = re.compile(r"([-−△]?)\s*(\d[\d,]*(?:\.\d+)?)\s*조(?:\s*(\d[\d,]*(?:\.\d+)?)\s*억)?")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_number(answer) -> float | None:
    """The answer as a number in the question's unit (억원 answers written with 조 are converted)."""
    if isinstance(answer, bool):
        return None
    if isinstance(answer, (int, float)):
        return float(answer)
    text = str(answer or "").strip()
    jo = _JO.search(text)
    if jo:
        v = _num(jo.group(2)) * 10_000 + (_num(jo.group(3)) if jo.group(3) else 0.0)
        return -v if jo.group(1) else v
    m = _NUM.search(_PERIOD.sub(" ", text)) or _NUM.search(text)
    if not m:
        return None
    raw = m.group(0).replace(" ", "").replace(",", "").replace("−", "-").replace("△", "-")
    try:
        v = float(raw)
    except ValueError:
        return None
    # "(1,234)" is a negative number in Korean filings
    if text.startswith("(") and text.rstrip().endswith(")") and v > 0:
        v = -v
    return v


def within(pred: float, gold: float, tol_abs: float, tol_rel: float) -> bool:
    return abs(pred - gold) <= max(tol_abs, tol_rel * abs(gold))


def score(question: dict, answer) -> dict:
    """Return {'correct': bool, 'pred': ..., 'trap': name|None, 'rel_err': float|None}."""
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        return {"correct": False, "pred": None, "trap": None, "rel_err": None, "status": "no_answer"}
    if question["answer_type"] == "abstain":
        ok = is_abstain(answer)
        return {"correct": ok, "pred": str(answer)[:60], "trap": None if ok else "answered_unanswerable",
                "rel_err": None, "status": "correct" if ok else "wrong"}
    if is_abstain(answer):
        return {"correct": False, "pred": str(answer)[:60], "trap": "abstained", "rel_err": None, "status": "abstained"}
    if question["answer_type"] == "entity":
        text = str(answer)
        names = question["companies"]
        hits = [n for n in names if n in text]
        # "한빛전자" contains no other candidate name, but guard against substrings anyway
        hits = [h for h in hits if not any(h != o and h in o and o in text for o in names)]
        correct = hits == [question["gold"]]
        trap = None
        if not correct:
            for t, v in question.get("traps", {}).items():
                if hits == [v]:
                    trap = t
        return {"correct": correct, "pred": text[:60], "trap": trap, "rel_err": None,
                "status": "correct" if correct else "wrong"}
    pred = parse_number(answer)
    if pred is None:
        return {"correct": False, "pred": str(answer)[:60], "trap": None, "rel_err": None, "status": "unparsable"}
    gold = float(question["gold"])
    correct = within(pred, gold, question["tol_abs"], question["tol_rel"])
    rel = abs(pred - gold) / abs(gold) if gold else None
    trap = None
    if not correct:
        for t, v in question.get("traps", {}).items():
            if within(pred, float(v), question["tol_abs"], max(question["tol_rel"], 0.002)):
                trap = t
                break
        if trap is None and gold and pred and question.get("unit") == "억원":
            # right digits, wrong power of ten: e.g. a 백만원 or 천원 figure reported as 억원
            for k in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5):
                if abs(pred / (gold * 10 ** k) - 1) <= 0.003:
                    trap = "unit_slip"
                    break
    return {"correct": correct, "pred": pred, "trap": trap, "rel_err": rel,
            "status": "correct" if correct else "wrong"}

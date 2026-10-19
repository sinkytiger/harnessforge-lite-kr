"""Questions with gold answers computed from the printed figures, plus planted traps.

Every question records:

* ``calc``: the facts (doc, offset, printed value, unit) and the expression that gives the gold
  answer. The reference (oracle) policy replays exactly this, so the test suite proves each
  question is answerable with the tools inside the round budget.
* ``traps``: answers a careless reader would give (the figure before a correction, the 잠정
  figure, the 별도 instead of 연결 statement, the cumulative instead of the 3-month column, a unit
  slip). They are used only for failure analysis after scoring, never shown to the agent.
"""

from __future__ import annotations

import random

from ..calc import evaluate
from .finance import CompanyFinancials

TO_EOK = {"백만원": 100, "천원": 100_000, "억원": 1}
EOK_SPEC = "억원 단위로 소수점 첫째 자리까지 숫자만 답하시오."
PCT_SPEC = "% 단위로 소수점 둘째 자리까지 숫자만 답하시오(감소·손실이면 음수)."
BASIS = "최종 확정 공시 기준으로"


def _fact_ref(f: dict) -> dict:
    return {k: f[k] for k in ("key", "doc_id", "offset", "line_start", "printed", "unit")}


def _eok_expr(i: int, unit: str) -> str:
    d = TO_EOK[unit]
    return f"F{i}" if d == 1 else f"F{i} / {d}"


class QuestionMaker:
    def __init__(self, corpus, fin: CompanyFinancials, rng: random.Random) -> None:
        self.c = corpus
        self.fin = fin
        self.s = fin.spec
        self.rng = rng

    def canon(self, basis: str, metric: str, period: str) -> dict:
        return self.c.canonical_fact((self.s.key, basis, metric, period))

    def superseded(self, basis: str, metric: str, period: str) -> dict | None:
        occ = [f for f in self.c.occurrences((self.s.key, basis, metric, period))
               if self.c.by_id[f["doc_id"]].get("corrected_by")]
        return occ[0] if occ else None

    def prelim(self, metric: str) -> dict | None:
        occ = [f for f in self.c.occurrences((self.s.key, "연결", metric, "FY2025"))
               if self.c.by_id[f["doc_id"]]["kind"] == "prelim"]
        return occ[0] if occ else None

    @staticmethod
    def value(expr: str, facts: list[dict]) -> float:
        return evaluate(expr, {f"F{i}": f["printed"] for i, f in enumerate(facts)})

    def make(self, qtype: str, **kw) -> dict | None:
        s = self.s
        name = s.name
        traps: dict[str, float] = {}
        if qtype in ("op_eok", "net_eok", "rev_eok"):
            metric = {"op_eok": "영업이익", "net_eok": "당기순이익", "rev_eok": "매출액"}[qtype]
            f = self.canon("연결", metric, "FY2025")
            facts, expr = [f], _eok_expr(0, f["unit"])
            text = f"{name}의 2025 사업연도 연결 기준 {metric}은 몇 억원인가? {BASIS} {EOK_SPEC}"
            if (o := self.superseded("연결", metric, "FY2025")):
                traps["before_correction"] = o["printed"] / TO_EOK[o["unit"]]
            if (p := self.prelim(metric)):
                traps["preliminary"] = p["printed"] / TO_EOK[p["unit"]]
            sep = self.canon("별도", metric, "FY2025")
            traps["separate_basis"] = sep["printed"] / TO_EOK[sep["unit"]]
            prev = self.canon("연결", metric, "FY2024")
            traps["wrong_year"] = prev["printed"] / TO_EOK[prev["unit"]]
            traps["unit_slip"] = f["printed"] / TO_EOK[f["unit"]] * 100
            unit = "억원"
        elif qtype == "op_margin":
            op, rev = self.canon("연결", "영업이익", "FY2025"), self.canon("연결", "매출액", "FY2025")
            facts, expr = [op, rev], "F0 / F1 * 100"
            text = f"{name}의 2025 사업연도 연결 기준 영업이익률(영업이익 ÷ 매출액)은 몇 %인가? {BASIS} {PCT_SPEC}"
            if (o := self.superseded("연결", "영업이익", "FY2025")):
                traps["before_correction"] = o["printed"] / rev["printed"] * 100
            p_op, p_rev = self.prelim("영업이익"), self.prelim("매출액")
            if p_op and p_rev:
                traps["preliminary"] = p_op["printed"] / p_rev["printed"] * 100
            so, sr = self.canon("별도", "영업이익", "FY2025"), self.canon("별도", "매출액", "FY2025")
            traps["separate_basis"] = so["printed"] / sr["printed"] * 100
            po, pr = self.canon("연결", "영업이익", "FY2024"), self.canon("연결", "매출액", "FY2024")
            traps["wrong_year"] = po["printed"] / pr["printed"] * 100
            unit = "%"
        elif qtype == "rev_growth":
            r25, r24 = self.canon("연결", "매출액", "FY2025"), self.canon("연결", "매출액", "FY2024")
            facts, expr = [r25, r24], "(F0 / F1 - 1) * 100"
            text = f"{name}의 2025 사업연도 연결 매출액은 전년 대비 몇 % 증가했는가? {BASIS} {PCT_SPEC}"
            if (p := self.prelim("매출액")):
                traps["preliminary"] = (p["printed"] * 100 / r24["printed"] - 1) * 100
            s25, s24 = self.canon("별도", "매출액", "FY2025"), self.canon("별도", "매출액", "FY2024")
            traps["separate_basis"] = (s25["printed"] / s24["printed"] - 1) * 100
            r23 = self.canon("연결", "매출액", "FY2023")
            traps["wrong_year"] = (r24["printed"] / r23["printed"] - 1) * 100
            unit = "%"
        elif qtype == "debt_ratio":
            li, eq = self.canon("연결", "부채총계", "FY2025"), self.canon("연결", "자본총계", "FY2025")
            facts, expr = [li, eq], "F0 / F1 * 100"
            text = f"{name}의 2025 사업연도 말 연결 기준 부채비율(부채총계 ÷ 자본총계)은 몇 %인가? {BASIS} {PCT_SPEC}"
            sl, se = self.canon("별도", "부채총계", "FY2025"), self.canon("별도", "자본총계", "FY2025")
            traps["separate_basis"] = sl["printed"] / se["printed"] * 100
            assets = self.canon("연결", "자산총계", "FY2025")
            traps["wrong_formula"] = li["printed"] / assets["printed"] * 100
            pl, pe = self.canon("연결", "부채총계", "FY2024"), self.canon("연결", "자본총계", "FY2024")
            traps["wrong_year"] = pl["printed"] / pe["printed"] * 100
            unit = "%"
        elif qtype == "sep_rev_eok":
            f = self.canon("별도", "매출액", "FY2024")
            facts, expr = [f], _eok_expr(0, f["unit"])
            text = f"{name}의 2024 사업연도 별도 기준 매출액은 몇 억원인가? {BASIS} {EOK_SPEC}"
            con = self.canon("연결", "매출액", "FY2024")
            traps["consolidated_basis"] = con["printed"] / TO_EOK[con["unit"]]
            nxt = self.canon("별도", "매출액", "FY2025")
            traps["wrong_year"] = nxt["printed"] / TO_EOK[nxt["unit"]]
            unit = "억원"
        elif qtype in ("q2_op_eok", "h1_rev_eok"):
            metric, period = ("영업이익", "2026Q2_3M") if qtype == "q2_op_eok" else ("매출액", "2026H1_CUM")
            f = self.canon("연결", metric, period)
            facts, expr = [f], _eok_expr(0, f["unit"])
            if qtype == "q2_op_eok":
                text = f"{name}의 2026년 2분기(4~6월, 3개월) 연결 기준 영업이익은 몇 억원인가? {BASIS} {EOK_SPEC}"
                other = self.canon("연결", metric, "2026H1_CUM")
                traps["cumulative_column"] = other["printed"] / TO_EOK[other["unit"]]
            else:
                text = f"{name}의 2026년 상반기(1~6월 누적) 연결 기준 매출액은 몇 억원인가? {BASIS} {EOK_SPEC}"
                other = self.canon("연결", metric, "2026Q2_3M")
                traps["three_month_column"] = other["printed"] / TO_EOK[other["unit"]]
            prev = self.canon("연결", metric, period.replace("2026", "2025"))
            traps["wrong_year"] = prev["printed"] / TO_EOK[prev["unit"]]
            sep = self.canon("별도", metric, period)
            traps["separate_basis"] = sep["printed"] / TO_EOK[sep["unit"]]
            wrong_unit = "백만원" if f["unit"] == "천원" else "천원"
            traps["unit_slip"] = f["printed"] / TO_EOK[wrong_unit]
            unit = "억원"
        elif qtype == "seg_share":
            seg = kw.get("segment") or self.rng.choice(s.segments)
            f, tot = self.canon("연결", f"부문매출:{seg}", "FY2025"), self.canon("연결", "부문매출:합계", "FY2025")
            facts, expr = [f, tot], "F0 / F1 * 100"
            text = (f"{name}의 2025 사업연도 연결 매출액 중 '{seg}' 부문 매출이 차지하는 비중은 몇 %인가? "
                    f"{BASIS} {PCT_SPEC}")
            pf, pt = self.canon("연결", f"부문매출:{seg}", "FY2024"), self.canon("연결", "부문매출:합계", "FY2024")
            traps["wrong_year"] = pf["printed"] / pt["printed"] * 100
            unit = "%"
        else:
            raise ValueError(qtype)
        gold = self.value(expr, facts)
        return {"qtype": qtype, "company_key": s.key, "companies": [name], "text": text, "unit": unit,
                "gold": gold, "answer_type": "number",
                "tol_abs": 0.15 if unit == "억원" else 0.05, "tol_rel": 0.002 if unit == "억원" else 0.0,
                "calc": {"expr": expr, "facts": [_fact_ref(f) for f in facts]},
                "traps": traps}


def _distinct(q: dict) -> dict:
    """Drop traps that would be scored correct anyway; they are not informative."""
    tol = max(q["tol_abs"], q["tol_rel"] * abs(q["gold"]))
    q["traps"] = {k: v for k, v in q["traps"].items() if abs(v - q["gold"]) > 2 * tol}
    return q


TYPE_POOL = ["debt_ratio", "sep_rev_eok", "seg_share", "h1_rev_eok", "rev_eok", "net_eok", "rev_growth"]


def generate_questions(corpus, fin_by_key: dict, rng: random.Random, per_company: int = 3) -> list[dict]:
    questions: list[dict] = []
    margins: dict[str, tuple[float, float | None]] = {}
    for key, fin in fin_by_key.items():
        s = fin.spec
        qm = QuestionMaker(corpus, fin, rng)
        wanted: list[str] = []
        if s.correction:
            wanted.append(rng.choice(["op_eok", "op_margin"]))
        if s.preliminary:
            wanted.append(rng.choice(["rev_growth", "net_eok"] if "op_margin" in wanted or "op_eok" in wanted
                                     else ["rev_growth", "op_eok", "net_eok"]))
        if s.quarterly_unit == "천원":
            wanted.append("q2_op_eok")
        pool = [t for t in TYPE_POOL if t not in wanted]
        rng.shuffle(pool)
        for t in pool:
            if len(wanted) >= per_company:
                break
            wanted.append(t)
        for t in wanted[:per_company]:
            q = _distinct(qm.make(t))
            q["split"] = s.split
            questions.append(q)
        op, rev = qm.canon("연결", "영업이익", "FY2025"), qm.canon("연결", "매출액", "FY2025")
        orig = qm.superseded("연결", "영업이익", "FY2025")
        margins[key] = (op["printed"] / rev["printed"] * 100,
                        orig["printed"] / rev["printed"] * 100 if orig else None)

    # Comparison questions: prefer pairs where reading the uncorrected report flips the answer.
    for split, n_pairs in (("search", 1), ("test", 2)):
        keys = [k for k, f in fin_by_key.items() if f.spec.split == split]
        pairs = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]]
        rng.shuffle(pairs)

        def flips(p: tuple) -> bool:
            a, b = p
            ma, oa = margins[a]
            mb, ob = margins[b]
            if oa is None and ob is None:
                return False
            return ((oa if oa is not None else ma) > (ob if ob is not None else mb)) != (ma > mb)

        pairs.sort(key=lambda p: (not flips(p), abs(margins[p[0]][0] - margins[p[1]][0]) < 0.5))
        for a, b in pairs[:n_pairs]:
            fa, fb = fin_by_key[a], fin_by_key[b]
            qa, qb = QuestionMaker(corpus, fa, rng), QuestionMaker(corpus, fb, rng)
            items = []
            for qm in (qa, qb):
                op, rev = qm.canon("연결", "영업이익", "FY2025"), qm.canon("연결", "매출액", "FY2025")
                items.append({"name": qm.s.name, "expr": "F0 / F1 * 100", "facts": [_fact_ref(op), _fact_ref(rev)]})
            winner = fa.spec.name if margins[a][0] > margins[b][0] else fb.spec.name
            loser = fb.spec.name if winner == fa.spec.name else fa.spec.name
            traps = {"before_correction": loser} if flips((a, b)) else {}
            questions.append({
                "qtype": "compare_margin", "company_key": f"{a}+{b}", "companies": [fa.spec.name, fb.spec.name],
                "text": (f"{fa.spec.name}와(과) {fb.spec.name} 중 2025 사업연도 연결 기준 영업이익률(영업이익 ÷ 매출액)이 "
                         f"더 높은 회사는 어디인가? {BASIS} 회사명만 답하시오."),
                "unit": "회사명", "gold": winner, "answer_type": "entity", "tol_abs": 0.0, "tol_rel": 0.0,
                "calc": {"compare": items, "pick": "max"}, "traps": traps, "split": split})

    order = {"search": 0, "test": 1}
    questions.sort(key=lambda q: (order[q["split"]], q["company_key"], q["qtype"]))
    counters = {"search": 0, "test": 0}
    for q in questions:
        counters[q["split"]] += 1
        q["qid"] = f"{'S' if q['split'] == 'search' else 'T'}{counters[q['split']]:02d}_{q['qtype']}"
    return questions

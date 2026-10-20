"""v2 questions: more types, more traps, unanswerable questions and a three-way split.

Every v2 question ends with the same abstention clause, so a question never signals by its wording
whether it can be answered. Unanswerable questions have the gold answer "알 수 없음".

Splits are by company: search (Harmony may look at gold answers), validation (for choosing rules
such as when to run Harness²) and test (reporting only).
"""

from __future__ import annotations

import random

from .finance import CompanyFinancials
from .questions import BASIS, EOK_SPEC, PCT_SPEC, TO_EOK, QuestionMaker, _distinct, _eok_expr, _fact_ref

ABSTAIN_CLAUSE = "공시에서 확인할 수 없으면 '알 수 없음'이라고 답하시오."
ABSTAIN_GOLD = "알 수 없음"
WON_SPEC = "원 단위 숫자만 답하시오(줄었으면 음수)."
FAKE_COMPANIES = ["가람정밀", "도담케미칼", "새벽모빌리티", "다올식품", "누리솔라", "한빛로직스", "초원바이오", "온누리항만"]
PREFIX = {"search": "S", "validation": "V", "test": "T"}
POOL = ["debt_ratio", "sep_rev_eok", "seg_share", "h1_rev_eok", "cagr_rev", "roe", "dps_change", "q3_3m_rev",
        "q4_op_derived", "rev_eok", "net_eok", "op_margin", "q2_op_eok", "rev_growth"]


class QuestionMakerV2(QuestionMaker):
    def superseded(self, basis: str, metric: str, period: str) -> dict | None:
        """The figure as first printed in an annual report that a [기재정정] filing replaced."""
        occ = [f for f in self.c.occurrences((self.s.key, basis, metric, period))
               if self.c.by_id[f["doc_id"]].get("corrected_by") and self.c.by_id[f["doc_id"]]["kind"] == "annual"]
        return occ[0] if occ else None

    def in_report(self, basis: str, metric: str, period: str, report: str) -> dict | None:
        occ = [f for f in self.c.occurrences((self.s.key, basis, metric, period))
               if self.c.by_id[f["doc_id"]]["report"] == report]
        return occ[0] if occ else None

    @staticmethod
    def eok(f: dict) -> float:
        return f["printed"] / TO_EOK[f["unit"]]

    def make(self, qtype: str, **kw) -> dict | None:
        s, name = self.s, self.s.name
        if qtype in ("cagr_rev", "q3_3m_rev", "q4_op_derived", "roe", "dps_change", "old_dps"):
            traps: dict[str, float] = {}
            if qtype == "cagr_rev":
                r25, r23 = self.canon("연결", "매출액", "FY2025"), self.canon("연결", "매출액", "FY2023")
                facts, expr = [r25, r23], "((F0 / F1) ** 0.5 - 1) * 100"
                text = f"{name}의 2023~2025 사업연도 연결 매출액 연평균 성장률(CAGR)은 몇 %인가? {BASIS} {PCT_SPEC}"
                traps["not_annualized"] = (r25["printed"] / r23["printed"] - 1) * 100
                r24 = self.canon("연결", "매출액", "FY2024")
                traps["yoy_instead"] = (r25["printed"] / r24["printed"] - 1) * 100
                unit = "%"
            elif qtype == "q3_3m_rev":
                f = self.canon("연결", "매출액", "2025Q3_3M")
                facts, expr = [f], _eok_expr(0, f["unit"])
                text = f"{name}의 2025년 3분기(7~9월, 3개월) 연결 기준 매출액은 몇 억원인가? {BASIS} {EOK_SPEC}"
                traps["cumulative_column"] = self.eok(self.canon("연결", "매출액", "2025Q3_CUM"))
                traps["wrong_year"] = self.eok(self.canon("연결", "매출액", "2024Q3_3M"))
                traps["separate_basis"] = self.eok(self.canon("별도", "매출액", "2025Q3_3M"))
                unit = "억원"
            elif qtype == "q4_op_derived":
                fy, cum = self.canon("연결", "영업이익", "FY2025"), self.canon("연결", "영업이익", "2025Q3_CUM")
                facts = [fy, cum]
                expr = f"F0 / {TO_EOK[fy['unit']]} - F1 / {TO_EOK[cum['unit']]}"
                text = f"{name}의 2025년 4분기(10~12월, 3개월) 연결 기준 영업이익은 몇 억원인가? {BASIS} {EOK_SPEC}"
                traps["annual_instead"] = self.eok(fy)
                traps["q3_instead"] = self.eok(self.canon("연결", "영업이익", "2025Q3_3M"))
                if (o := self.superseded("연결", "영업이익", "FY2025")):
                    traps["before_correction"] = self.eok(o) - self.eok(cum)
                unit = "억원"
            elif qtype == "roe":
                ni, e1, e0 = (self.canon("연결", "당기순이익", "FY2025"), self.canon("연결", "자본총계", "FY2025"),
                              self.canon("연결", "자본총계", "FY2024"))
                facts, expr = [ni, e1, e0], "F0 / ((F1 + F2) / 2) * 100"
                text = (f"{name}의 2025 사업연도 연결 기준 ROE(당기순이익 ÷ 기초·기말 평균 자본총계)는 몇 %인가? "
                        f"{BASIS} {PCT_SPEC}")
                traps["ending_equity_only"] = ni["printed"] / e1["printed"] * 100
                sn, s1, s0 = (self.canon("별도", "당기순이익", "FY2025"), self.canon("별도", "자본총계", "FY2025"),
                              self.canon("별도", "자본총계", "FY2024"))
                traps["separate_basis"] = sn["printed"] / ((s1["printed"] + s0["printed"]) / 2) * 100
                if (o := self.superseded("연결", "당기순이익", "FY2025")):
                    traps["before_correction"] = o["printed"] / ((e1["printed"] + e0["printed"]) / 2) * 100
                unit = "%"
            elif qtype == "dps_change":
                d1, d0 = self.canon("연결", "주당배당금", "FY2025"), self.canon("연결", "주당배당금", "FY2024")
                facts, expr = [d1, d0], "F0 - F1"
                text = f"{name}의 2025 사업연도 주당 현금배당금은 전년보다 몇 원 늘었는가? {BASIS} {WON_SPEC}"
                dm = self.canon("연결", "주당배당금", "FY2023")
                traps["wrong_year"] = d0["printed"] - dm["printed"]
                traps["level_instead"] = d1["printed"]
                unit = "원"
            else:  # old_dps: only the FY2023 report has the 2022 dividend, filed under the old name
                f = self.canon("연결", "주당배당금", "FY2022")
                facts, expr = [f], "F0"
                text = f"{name}의 2022 사업연도 주당 현금배당금은 몇 원인가? {BASIS} 원 단위 숫자만 답하시오."
                traps["wrong_year"] = self.canon("연결", "주당배당금", "FY2023")["printed"]
                unit = "원"
            gold = self.value(expr, facts)
            tol = {"억원": (0.15, 0.002), "%": (0.05, 0.0), "원": (0.5, 0.0)}[unit]
            return {"qtype": qtype, "company_key": s.key, "companies": [name], "text": text, "unit": unit,
                    "gold": gold, "answer_type": "number", "tol_abs": tol[0], "tol_rel": tol[1],
                    "calc": {"expr": expr, "facts": [_fact_ref(f) for f in facts]}, "traps": traps}
        q = super().make(qtype, **kw)
        if qtype == "rev_growth" and self.fin.spec.restated:
            orig = self.in_report("연결", "매출액", "FY2024", "사업보고서 (2024.12)")
            r25 = q["calc"]["facts"][0]
            if orig:
                q["traps"]["before_restatement"] = (r25["printed"] / TO_EOK[r25["unit"]] / (orig["printed"] / TO_EOK[orig["unit"]]) - 1) * 100
        if self.fin.prelim_corrected:
            for t_metric in ("매출액", "영업이익", "당기순이익"):
                if qtype in ({"매출액": "rev_eok", "영업이익": "op_eok", "당기순이익": "net_eok"}[t_metric],):
                    occ = [f for f in self.c.occurrences((s.key, "연결", t_metric, "FY2025"))
                           if self.c.by_id[f["doc_id"]]["kind"] == "prelim_correction"]
                    if occ:
                        q["traps"]["corrected_preliminary"] = occ[0]["printed"]
        return q


def _abstain(kind: str, company: str, company_key: str) -> dict:
    texts = {
        "future_period": f"{company}의 2026년 3분기(7~9월, 3개월) 연결 기준 매출액은 몇 억원인가? {BASIS} {EOK_SPEC}",
        "undisclosed_item": f"{company}의 2025 사업연도 연구개발비 중 정부출연금 수령액은 몇 억원인가? {BASIS} {EOK_SPEC}",
        "unknown_company": f"{company}의 2025 사업연도 연결 기준 매출액은 몇 억원인가? {BASIS} {EOK_SPEC}",
    }
    return {"qtype": f"abstain_{kind}", "company_key": company_key, "companies": [company], "text": texts[kind],
            "unit": "", "gold": ABSTAIN_GOLD, "answer_type": "abstain", "tol_abs": 0.0, "tol_rel": 0.0,
            "calc": {"abstain": True}, "traps": {}}


def _ranked(corpus, fins: dict, keys: list[str], rng: random.Random, pick: str) -> dict:
    items, margins = [], {}
    for k in keys:
        qm = QuestionMakerV2(corpus, fins[k], rng)
        op, rev = qm.canon("연결", "영업이익", "FY2025"), qm.canon("연결", "매출액", "FY2025")
        items.append({"name": qm.s.name, "expr": "F0 / F1 * 100", "facts": [_fact_ref(op), _fact_ref(rev)]})
        margins[qm.s.name] = op["printed"] / rev["printed"] * 100
    order = sorted(margins, key=lambda n: -margins[n])
    names = [fins[k].spec.name for k in keys]
    joined = ", ".join(names[:-1]) + f", {names[-1]}"
    if pick == "max":
        gold = order[0]
        text = (f"{joined} 중 2025 사업연도 연결 기준 영업이익률(영업이익 ÷ 매출액)이 가장 높은 회사는 어디인가? "
                f"{BASIS} 회사명만 답하시오.")
        traps = {"second_instead": order[1]}
    else:
        gold = order[1]
        text = (f"{joined} 중 2025 사업연도 연결 기준 영업이익률(영업이익 ÷ 매출액)이 두 번째로 높은 회사는 어디인가? "
                f"{BASIS} 회사명만 답하시오.")
        traps = {"first_instead": order[0]}
    return {"qtype": "compare_margin" if pick == "max" else "rank2_margin", "company_key": "+".join(keys),
            "companies": names, "text": text, "unit": "회사명", "gold": gold, "answer_type": "entity",
            "tol_abs": 0.0, "tol_rel": 0.0, "calc": {"compare": items, "pick": pick}, "traps": traps}


def generate_questions_v2(corpus, fins: dict[str, CompanyFinancials], rng: random.Random, per_company: int = 5) -> list[dict]:
    questions: list[dict] = []
    for split in ("search", "validation", "test"):
        keys = [k for k, f in fins.items() if f.spec.split == split]
        counts: dict[str, int] = {}
        for k in keys:
            fin, s = fins[k], fins[k].spec
            qm = QuestionMakerV2(corpus, fin, rng)
            wanted: list[str] = []
            if s.old_name:
                wanted.append("old_dps")
            if s.correction:
                wanted.append(rng.choice(["op_eok", "op_margin", "q4_op_derived", "roe"]))
            if s.restated and "rev_growth" not in wanted:
                wanted.append("rev_growth")
            if s.preliminary:
                wanted.append(rng.choice([t for t in ("net_eok", "rev_growth", "rev_eok") if t not in wanted]))
            if s.quarterly_unit == "천원":
                wanted.append(rng.choice([t for t in ("q2_op_eok", "q3_3m_rev", "q4_op_derived") if t not in wanted]))
            if s.annual_unit == "천원":
                wanted.append(rng.choice([t for t in ("rev_eok", "op_eok", "roe") if t not in wanted]))
            wanted = list(dict.fromkeys(wanted))[:per_company]
            pool = [t for t in POOL if t not in wanted]
            rng.shuffle(pool)
            pool.sort(key=lambda t: counts.get(t, 0))
            for t in pool:
                if len(wanted) >= per_company:
                    break
                wanted.append(t)
            for t in wanted:
                q = _distinct(qm.make(t))
                q["split"] = split
                counts[t] = counts.get(t, 0) + 1
                questions.append(q)
        n_rank = 1 if split != "test" else 2
        for pick in ("max", "second"):
            for _ in range(n_rank):
                group = rng.sample(keys, 4 if pick == "second" else 2)
                q = _ranked(corpus, fins, group, rng, pick)
                q["split"] = split
                questions.append(q)
        n_abstain = {"search": 4, "validation": 3, "test": 8}[split]
        kinds = ["future_period", "undisclosed_item", "unknown_company"]
        fakes = list(FAKE_COMPANIES)
        rng.shuffle(fakes)
        for i in range(n_abstain):
            kind = kinds[i % 3]
            if kind == "unknown_company":
                q = _abstain(kind, fakes.pop(), "none")
            else:
                k = rng.choice(keys)
                q = _abstain(kind, fins[k].spec.name, k)
            q["split"] = split
            questions.append(q)

    for q in questions:
        q["text"] = f"{q['text']} {ABSTAIN_CLAUSE}"
    order = {"search": 0, "validation": 1, "test": 2}
    questions.sort(key=lambda q: (order[q["split"]], q["company_key"], q["qtype"]))
    counters = {s: 0 for s in order}
    for q in questions:
        counters[q["split"]] += 1
        q["qid"] = f"{PREFIX[q['split']]}{counters[q['split']]:02d}_{q['qtype']}"
    return questions

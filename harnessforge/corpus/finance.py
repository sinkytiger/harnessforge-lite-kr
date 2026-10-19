"""Financial figures for fictional companies.

Annual figures are integers in 백만원 (KRW million). Quarterly figures are integers in 천원
(KRW thousand). Every income-statement line is derived from a few sampled drivers, so the usual
identities hold exactly (매출총이익 = 매출액 - 매출원가, 영업이익 = 매출총이익 - 판관비, ...).
Quarterly lines are additive, so the 2025 fourth quarter is the annual figure minus Q1-Q3.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

IS_LINES = ["매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익", "금융수익", "금융비용",
            "기타수익", "기타비용", "법인세비용차감전순이익", "법인세비용", "당기순이익"]
BS_LINES = ["유동자산", "비유동자산", "자산총계", "유동부채", "비유동부채", "부채총계",
            "자본금", "이익잉여금", "기타자본", "자본총계"]
YEARS = (2023, 2024, 2025)


@dataclass
class CompanySpec:
    key: str
    name: str
    code: str
    sector: str
    segments: list[str]
    products: list[str]
    ceo: str
    city: str
    founded: int
    # Trait flags, set by the corpus builder.
    correction: bool = False       # a [기재정정] FY2025 annual report restates 영업이익 and 당기순이익
    preliminary: bool = False      # a FY2025 잠정실적 공정공시 whose figures differ from the audited report
    quarterly_unit: str = "백만원"  # unit of the 2026 quarterly and half-year statements: 천원 or 백만원
    split: str = "test"

    def fiscal_no(self, year: int) -> int:
        return year - self.founded + 1


@dataclass
class CompanyFinancials:
    spec: CompanySpec
    annual: dict = field(default_factory=dict)            # (basis, year) -> {line: 백만원}
    annual_original: dict = field(default_factory=dict)   # (basis, year) as first filed, when later corrected
    segments: dict = field(default_factory=dict)          # year -> {segment: 백만원}, consolidated revenue split
    quarters: dict = field(default_factory=dict)          # (basis, year, q) -> {line: 천원}, 3-month figures
    preliminary: dict = field(default_factory=dict)       # line -> 억원 (FY2025, consolidated)
    dps: dict = field(default_factory=dict)               # year -> 원 per share
    employees: dict = field(default_factory=dict)         # year -> headcount


def _close_is(lines: dict, tax_rate: float) -> dict:
    pretax = lines["영업이익"] + lines["금융수익"] - lines["금융비용"] + lines["기타수익"] - lines["기타비용"]
    tax = int(round(max(pretax, 0) * tax_rate))
    out = {k: v for k, v in lines.items() if not k.startswith("_")}
    out["법인세비용차감전순이익"] = pretax
    out["법인세비용"] = tax
    out["당기순이익"] = pretax - tax
    out["_tax_rate"] = tax_rate
    return out


def _income_statement(rev: int, gm: float, om: float, rng: random.Random) -> dict:
    """A consistent income statement from revenue and gross/operating margins."""
    cogs = int(round(rev * (1 - gm)))
    gross = rev - cogs
    op = int(round(rev * om))
    lines = {"매출액": rev, "매출원가": cogs, "매출총이익": gross, "판매비와관리비": gross - op, "영업이익": op,
             "금융수익": int(round(rev * rng.uniform(0.002, 0.012))),
             "금융비용": int(round(rev * rng.uniform(0.003, 0.02))),
             "기타수익": int(round(rev * rng.uniform(0.001, 0.008))),
             "기타비용": int(round(rev * rng.uniform(0.001, 0.010)))}
    return _close_is(lines, tax_rate=rng.uniform(0.19, 0.24))


def restate_operating_profit(lines: dict, new_op: int) -> dict:
    """Change 영업이익 by moving the difference into 판관비; the lines below it follow."""
    out = dict(lines)
    out["판매비와관리비"] = out["매출총이익"] - new_op
    out["영업이익"] = new_op
    return _close_is(out, lines.get("_tax_rate", 0.22))


def _balance_sheet(rev: int, rng: random.Random, prev: dict | None) -> dict:
    if prev is None:
        assets = int(round(rev * rng.uniform(0.8, 1.9)))
    else:
        assets = int(round(prev["자산총계"] * rng.uniform(0.95, 1.18)))
    liab = int(round(assets * rng.uniform(0.25, 0.62)))
    equity = assets - liab
    cur_a = int(round(assets * rng.uniform(0.35, 0.6)))
    cur_l = int(round(liab * rng.uniform(0.45, 0.75)))
    capital = prev["자본금"] if prev else int(round(equity * rng.uniform(0.04, 0.12)))
    retained = int(round((equity - capital) * rng.uniform(0.6, 0.9)))
    return {"유동자산": cur_a, "비유동자산": assets - cur_a, "자산총계": assets, "유동부채": cur_l,
            "비유동부채": liab - cur_l, "부채총계": liab, "자본금": capital, "이익잉여금": retained,
            "기타자본": equity - capital - retained, "자본총계": equity}


def split_total(total: int, n: int, rng: random.Random, low: float = 0.12) -> list[int]:
    weights = [rng.uniform(low, 1.0) for _ in range(n)]
    s = sum(weights)
    parts = [int(round(total * w / s)) for w in weights[:-1]]
    parts.append(total - sum(parts))
    return parts


def _quarter_lines(annual: dict, base_rev: float, rng: random.Random) -> dict:
    om = annual["영업이익"] / max(annual["매출액"], 1) + rng.uniform(-0.03, 0.03)
    gm = max(annual["매출총이익"] / max(annual["매출액"], 1) + rng.uniform(-0.02, 0.02), om + 0.06)
    lines = _income_statement(int(round(base_rev)), gm, om, rng)
    return {k: v for k, v in lines.items() if not k.startswith("_")}


def generate_financials(spec: CompanySpec, rng: random.Random) -> CompanyFinancials:
    fin = CompanyFinancials(spec=spec)
    rev = rng.randint(80_000, 3_800_000)  # 800억 ~ 3.8조 원, in 백만원
    gm = rng.uniform(0.14, 0.42)
    om = rng.uniform(-0.03, 0.16)
    sep_ratio = rng.uniform(0.55, 0.88)
    prev_bs: dict = {"연결": None, "별도": None}
    for i, year in enumerate(YEARS):
        if i:
            rev = int(round(rev * (1 + rng.uniform(-0.12, 0.32))))
            om = min(max(om + rng.uniform(-0.04, 0.04), -0.06), 0.2)
            gm = min(max(gm + rng.uniform(-0.03, 0.03), om + 0.08), 0.5)
        con = _income_statement(rev, max(gm, om + 0.08), om, rng)
        sep_rev = int(round(rev * sep_ratio * rng.uniform(0.97, 1.03)))
        sep_om = om + rng.choice([-1, 1]) * rng.uniform(0.012, 0.035)
        sep = _income_statement(sep_rev, max(gm + rng.uniform(-0.02, 0.02), sep_om + 0.08), sep_om, rng)
        fin.annual[("연결", year)] = con | _balance_sheet(rev, rng, prev_bs["연결"])
        fin.annual[("별도", year)] = sep | _balance_sheet(sep_rev, rng, prev_bs["별도"])
        prev_bs = {"연결": fin.annual[("연결", year)], "별도": fin.annual[("별도", year)]}
        fin.segments[year] = dict(zip(spec.segments, split_total(rev, len(spec.segments), rng)))
        fin.dps[year] = rng.choice([0, 100, 150, 200, 250, 300, 400, 500, 700, 1000])
        fin.employees[year] = rng.randint(180, 4200)

    if spec.correction:
        # The FY2025 report as first filed carried a wrong 영업이익 (and so a wrong 당기순이익).
        true = fin.annual[("연결", 2025)]
        sign = rng.choice([-1, 1])
        delta = max(abs(true["영업이익"]), true["매출액"] * 0.02) * rng.uniform(0.07, 0.16) * sign
        wrong = restate_operating_profit(true, int(round(true["영업이익"] + delta)))
        fin.annual_original[("연결", 2025)] = wrong | {k: true[k] for k in BS_LINES}

    for basis in ("연결", "별도"):
        annual = fin.annual[(basis, 2025)]
        shares = split_total(1000, 4, rng, low=0.7)
        parts = {q: _quarter_lines(annual, annual["매출액"] * shares[q - 1], rng) for q in (1, 2, 3)}
        parts[4] = {k: annual[k] * 1000 - sum(parts[q][k] for q in (1, 2, 3)) for k in IS_LINES}
        for q in (1, 2, 3, 4):
            fin.quarters[(basis, 2025, q)] = parts[q]
        base_q = annual["매출액"] * 1000 / 4
        for q in (1, 2):
            fin.quarters[(basis, 2026, q)] = _quarter_lines(
                annual, base_q * rng.uniform(0.86, 1.22) + rng.randint(0, 999), rng)

    if spec.preliminary:
        true = fin.annual[("연결", 2025)]
        orig = fin.annual_original.get(("연결", 2025), true)

        def eok(v: int, lo: float, hi: float) -> int:
            return int(round(v * (1 + rng.choice([-1, 1]) * rng.uniform(lo, hi)) / 100))

        fin.preliminary = {"매출액": eok(true["매출액"], 0.015, 0.04),
                           "영업이익": eok(orig["영업이익"], 0.04, 0.09),
                           "법인세비용차감전순이익": eok(orig["법인세비용차감전순이익"], 0.04, 0.09),
                           "당기순이익": eok(orig["당기순이익"], 0.04, 0.10)}
    return fin

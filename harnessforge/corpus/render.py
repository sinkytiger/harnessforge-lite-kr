"""Render DART-style filings as plain text and record where every key figure is printed.

The documents imitate the layout of Korean periodic reports (사업보고서, 분기/반기보고서), a
[기재정정] correction filing and a 잠정실적 공정공시. They are long on purpose: boilerplate sections
with incidental numbers make the corpus much larger than a small model's context window, so the
agent has to search and read instead of stuffing everything into the prompt.

Every document carries a notice that it is synthetic and unrelated to any real company.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .finance import BS_LINES, IS_LINES, CompanyFinancials

NOTICE = "※ 본 문서는 연구용 합성 데이터입니다. 실존 기업·공시와 무관하며 모든 수치는 가상입니다."


def fmt(v: int) -> str:
    return f"△{abs(v):,}" if v < 0 else f"{v:,}"


def eok_text(v_mil: int) -> str:
    """Narrative amount in 억원 from a 백만원 figure."""
    return f"{v_mil / 100:,.0f}억원"


@dataclass
class Fact:
    key: tuple          # (company_key, basis, metric, period)
    doc_id: str
    offset: int         # character offset of the printed number
    line_start: int
    printed: int        # the integer as printed, in `unit`
    unit: str

    def to_json(self) -> dict:
        return {"key": list(self.key), "doc_id": self.doc_id, "offset": self.offset,
                "line_start": self.line_start, "printed": self.printed, "unit": self.unit}


@dataclass
class Document:
    doc_id: str
    company_key: str
    company: str
    code: str
    kind: str           # annual | annual_correction | q1 | half | prelim
    report: str         # display name, e.g. "사업보고서 (2025.12)"
    filed: str          # YYYY.MM.DD
    rcept_no: str
    corrects: str | None = None
    corrected_by: str | None = None
    text: str = ""
    facts: list = field(default_factory=list)

    @property
    def title(self) -> str:
        return f"{self.company} | {self.report} | 제출 {self.filed}"

    def to_json(self) -> dict:
        return {"doc_id": self.doc_id, "company_key": self.company_key, "company": self.company,
                "code": self.code, "kind": self.kind, "report": self.report, "filed": self.filed,
                "rcept_no": self.rcept_no, "corrects": self.corrects, "corrected_by": self.corrected_by,
                "text": self.text}


class Builder:
    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self.parts: list[str] = []
        self.n = 0

    def line(self, s: str = "") -> None:
        self.parts.append(s + "\n")
        self.n += len(s) + 1

    def lines(self, rows: list[str]) -> None:
        for r in rows:
            self.line(r)

    def para(self, sentences: list[str]) -> None:
        self.line(" ".join(sentences))
        self.line()

    def row(self, label: str, values: list[int], unit: str, keys: list) -> None:
        cells = [fmt(v) for v in values]
        s = label + " | " + " | ".join(cells)
        pos = self.n + len(label) + 3
        for v, key, cell in zip(values, keys, cells):
            if key is not None:
                self.doc.facts.append(Fact(key=key, doc_id=self.doc.doc_id, offset=pos + (1 if v < 0 else 0),
                                           line_start=self.n, printed=v, unit=unit))
            pos += len(cell) + 3
        self.line(s)

    def text(self) -> str:
        return "".join(self.parts)


# ---------------------------------------------------------------------------------------------------
# Boilerplate banks (incidental numbers are noise, never asked about)

REGIONS = ["국내", "북미", "유럽", "중국", "동남아시아", "일본", "중동", "중남미"]
RISK = [
    "당사는 환율 변동에 따른 외화환산손익 위험에 노출되어 있으며, 주요 통화는 USD, EUR, JPY입니다.",
    "원재료 가격의 변동은 매출원가에 직접적인 영향을 미치므로 장기 공급계약과 복수 공급처 전략으로 대응하고 있습니다.",
    "당사는 변동금리부 차입금에 대하여 금리스왑 계약을 일부 체결하여 이자율 변동 위험을 관리하고 있습니다.",
    "주요 거래처에 대한 매출 의존도가 높아 거래처의 경영환경 변화가 당사 실적에 영향을 줄 수 있습니다.",
    "신용위험은 거래상대방이 계약조건상 의무사항을 지키지 못하였을 때 발생하며, 당사는 신용등급에 따라 거래한도를 관리합니다.",
    "유동성위험 관리를 위하여 단기 및 중장기 자금관리계획을 수립하고 현금유출입 예산과 실제를 주기적으로 대조합니다.",
    "경기 둔화에 따른 수요 감소, 경쟁 심화에 따른 판가 하락은 수익성에 부정적인 영향을 미칠 수 있습니다.",
    "당사는 파생상품을 매매목적이 아닌 위험회피 목적으로만 이용하며, 내부 위험관리 규정에 따라 승인 절차를 거칩니다.",
]
GOV = [
    "이사회는 사내이사 {a}명, 사외이사 {b}명으로 구성되어 있으며 이사회 의장은 {chair}입니다.",
    "당해 사업연도 중 이사회는 총 {m}회 개최되었고, 사외이사의 평균 출석률은 {att}%입니다.",
    "이사회 내 위원회로 감사위원회, 사외이사후보추천위원회, 보상위원회를 두고 있습니다.",
    "감사위원회는 전원 사외이사로 구성되며, 위원 중 {fin}명은 회계 또는 재무 전문가입니다.",
    "당사는 정관에 따라 집중투표제를 채택하지 않고 있으며 서면투표제를 도입하고 있습니다.",
    "주주총회 소집공고는 주주총회일 {d}일 전에 전자공시시스템과 당사 홈페이지에 게재하였습니다.",
]
HIST = [
    "{y}년 {m}월: 본사 사옥 이전",
    "{y}년 {m}월: 제{n}공장 준공",
    "{y}년 {m}월: 코스닥시장 상장",
    "{y}년 {m}월: 해외 현지법인 설립 ({region})",
    "{y}년 {m}월: 기업부설연구소 인증",
    "{y}년 {m}월: ISO 14001 인증 취득",
    "{y}년 {m}월: 대표이사 변경",
    "{y}년 {m}월: 유가증권시장 이전 상장",
    "{y}년 {m}월: 무상증자 실시",
    "{y}년 {m}월: 우수 협력사 표창 수상",
]
NOTES = [
    "연결실체의 재무제표는 한국채택국제회계기준에 따라 작성되었으며, 공정가치로 측정되는 일부 금융상품을 제외하고 역사적 원가를 기준으로 작성되었습니다.",
    "재고자산은 취득원가와 순실현가능가치 중 낮은 금액으로 측정하며, 단위원가는 총평균법으로 결정합니다.",
    "유형자산은 원가에서 감가상각누계액과 손상차손누계액을 차감하여 표시하며, 건물은 {a}년, 기계장치는 {b}년의 내용연수로 정액법 상각합니다.",
    "리스이용자로서 연결실체는 리스개시일에 사용권자산과 리스부채를 인식하며, 단기리스와 소액자산 리스에는 인식 면제를 적용합니다.",
    "수익은 고객과의 계약에서 약속한 재화나 용역을 고객에게 이전하여 수행의무를 이행할 때 인식합니다.",
    "금융자산은 사업모형과 계약상 현금흐름 특성에 따라 상각후원가, 기타포괄손익-공정가치, 당기손익-공정가치로 분류합니다.",
    "확정급여채무의 현재가치는 예측단위적립방식으로 산정하며, 할인율은 보고기간말 우량회사채 수익률 {r}%를 적용하였습니다.",
    "당기 중 인식한 감가상각비는 {dep}백만원이며, 이 중 {dep2}백만원은 매출원가에 포함되어 있습니다.",
    "영업부문은 최고영업의사결정자에게 보고되는 내부보고 자료와 동일한 방식으로 보고하고 있습니다.",
    "법인세비용은 당기법인세와 이연법인세로 구성되며, 일시적차이에 대하여 이연법인세자산과 부채를 인식합니다.",
]
MARKET = [
    "{sector} 산업은 {region} 시장의 수요 회복과 함께 완만한 성장이 예상되며, 당사는 {product} 중심으로 대응하고 있습니다.",
    "국내 {sector} 시장은 상위 {k}개사가 전체 시장의 약 {pct}%를 점유하는 과점 구조입니다.",
    "당사의 {product} 국내 시장점유율은 약 {pct2}% 수준으로 추정됩니다(당사 추정, 업계 자료 기준).",
    "주요 경쟁 요소는 가격, 품질, 납기 대응력이며 당사는 {region} 생산거점을 통해 원가 경쟁력을 확보하고 있습니다.",
    "{sector} 업종은 계절적 요인보다 전방 산업의 투자 주기에 따라 실적 변동이 나타나는 경향이 있습니다.",
    "정부의 {policy} 정책은 중장기적으로 당사 사업에 우호적인 환경을 조성할 것으로 판단됩니다.",
]
POLICIES = ["탄소중립", "공급망 안정화", "디지털 전환", "수출 지원", "소재·부품 국산화", "바이오헬스 육성"]
RND = [
    "당사는 기업부설연구소를 운영하고 있으며 연구개발 인력은 {n}명입니다.",
    "당기 연구개발비용은 {rnd}백만원으로 매출액 대비 {pct}% 수준입니다.",
    "주요 연구과제로 차세대 {product} 개발, 공정 자동화, 품질 예측 모델 고도화를 진행하고 있습니다.",
    "당사는 현재 국내외 특허 {pat}건을 보유하고 있으며, 당기 중 {newpat}건을 신규 등록하였습니다.",
    "{region} 소재 고객사와 {product} 공동개발 계약을 체결하였으며 계약기간은 {years}년입니다.",
]
AUDIT = [
    "외부감사인은 {auditor}이며, 당기 감사의견은 적정입니다.",
    "핵심감사사항으로 수익인식의 기간귀속과 재고자산 평가를 선정하였습니다.",
    "당기 감사보수는 {fee}백만원이며, 감사 소요시간은 {hours}시간입니다.",
    "내부회계관리제도 감사 결과 중요한 취약점은 발견되지 않았습니다.",
]
AUDITORS = ["가온회계법인", "누리회계법인", "다솜회계법인", "바른숲회계법인", "새봄회계법인"]
CHAIRS = ["대표이사", "사외이사", "사내이사"]


class Renderer:
    def __init__(self, fin: CompanyFinancials, rng: random.Random) -> None:
        self.fin = fin
        self.s = fin.spec
        self.rng = rng

    # -- small helpers
    def pick(self, bank: list[str], k: int, **extra) -> list[str]:
        r = self.rng
        out = []
        for t in r.sample(bank, min(k, len(bank))):
            out.append(t.format(
                a=r.randint(2, 5), b=r.randint(1, 4), m=r.randint(6, 14), att=r.randint(88, 100), fin=r.randint(1, 2),
                d=r.choice([14, 15, 21]), chair=r.choice(CHAIRS), r=round(r.uniform(3.1, 5.2), 2),
                dep=r.randint(1_000, 90_000), dep2=r.randint(500, 60_000), sector=self.s.sector,
                region=r.choice(REGIONS), product=r.choice(self.s.products), k=r.randint(3, 6),
                pct=round(r.uniform(35, 80), 1), pct2=round(r.uniform(3, 28), 1), policy=r.choice(POLICIES),
                n=r.randint(12, 380), rnd=r.randint(800, 120_000), pat=r.randint(10, 600),
                newpat=r.randint(1, 40), years=r.randint(2, 7), auditor=r.choice(AUDITORS),
                fee=r.randint(60, 900), hours=r.randint(900, 9000), **extra))
        return out

    def cover(self, b: Builder, title: str, period: str, year_no: str) -> None:
        b.lines([title, NOTICE, "", f"({year_no})", period, "",
                 f"회사명: {self.s.name}", f"종목코드: {self.s.code}", f"대표이사: {self.s.ceo}",
                 f"본점소재지: {self.s.city}", f"접수번호: {b.doc.rcept_no}", f"제출일: {b.doc.filed}", ""])

    def overview(self, b: Builder, year: int, short: bool = False) -> None:
        s, r = self.s, self.rng
        b.line("I. 회사의 개요")
        b.line("1. 회사의 개요")
        b.para([f"{s.name}(이하 '당사')는 {s.founded}년에 설립되었으며 {s.sector} 사업을 영위하고 있습니다.",
                f"당사의 본점은 {s.city}에 소재하고 있으며, 주요 사업부문은 {', '.join(s.segments)}입니다.",
                f"보고서 작성기준일 현재 연결대상 종속회사는 {r.randint(2, 14)}개사입니다."] +
               self.pick(MARKET, 1))
        if short:
            return
        b.line("2. 회사의 연혁")
        for t in r.sample(HIST, 6):
            b.line(" - " + t.format(y=r.randint(s.founded, year), m=r.randint(1, 12), n=r.randint(2, 5),
                                   region=r.choice(REGIONS)))
        b.line()
        b.line("3. 자본금 변동사항")
        b.para([f"보고서 작성기준일 현재 당사의 자본금은 {self.fin.annual[('연결', year)]['자본금']:,}백만원이며,",
                f"최근 5사업연도 중 자본금 변동은 {r.choice(['없습니다', '무상증자 1건이 있습니다', '전환사채 전환 2건이 있습니다'])}."])
        b.line("4. 주식의 총수 등")
        shares = r.randint(8_000_000, 90_000_000)
        b.para([f"발행할 주식의 총수는 {shares * 4:,}주이며, 현재까지 발행한 주식의 총수는 보통주 {shares:,}주입니다.",
                f"자기주식은 {r.randint(0, shares // 50):,}주를 보유하고 있습니다."])
        b.line("5. 정관에 관한 사항")
        b.para([f"최근 정관 변경일은 {year}년 03월 {r.randint(10, 29)}일이며, 사업목적 추가 및 전자증권 관련 조문을 정비하였습니다."])

    def business(self, b: Builder, year: int, short: bool = False) -> None:
        s, r, fin = self.s, self.rng, self.fin
        b.line("II. 사업의 내용")
        b.line("1. 사업의 개요")
        b.para(self.pick(MARKET, 4))
        b.para(self.pick(MARKET, 2) + self.pick(RND, 2))
        b.line("2. 주요 제품 및 서비스")
        b.para([f"당사의 주요 제품은 {', '.join(s.products)} 등이며, {r.choice(REGIONS)} 및 {r.choice(REGIONS)} 지역에 판매하고 있습니다."])
        if short:
            return
        b.line("3. 원재료 및 생산설비")
        b.para([f"주요 원재료의 당기 평균 매입가격은 전기 대비 {r.uniform(-12, 18):.1f}% 변동하였습니다.",
                f"당사는 {r.randint(2, 6)}개의 생산공장을 운영하고 있으며, 당기 평균 가동률은 {r.randint(62, 97)}%입니다.",
                f"당기 중 생산설비에 대한 신규 투자액은 {r.randint(1_000, 150_000):,}백만원입니다."])
        b.line("4. 매출 및 수주상황")
        b.line("가. 사업부문별 매출실적 (연결)")
        b.line("(단위: 백만원)")
        y3 = [year - 2, year - 1, year] if year - 2 in fin.segments else [y for y in (year - 1, year) if y in fin.segments]
        cols = list(reversed(y3))
        b.line("사업부문 | " + " | ".join(f"제 {s.fiscal_no(y)} 기 ({y}년)" for y in cols))
        for seg in s.segments:
            b.row(seg, [fin.segments[y][seg] for y in cols], "백만원",
                  [(s.key, "연결", f"부문매출:{seg}", f"FY{y}") for y in cols])
        b.row("합계", [sum(fin.segments[y].values()) for y in cols], "백만원",
              [(s.key, "연결", "부문매출:합계", f"FY{y}") for y in cols])
        b.line()
        b.para([f"당기말 수주잔고는 {r.randint(5_000, 2_500_000):,}백만원이며, 이 중 {r.choice(REGIONS)} 지역 비중은 {r.randint(5, 60)}%입니다."])
        b.line("5. 위험관리 및 파생거래")
        b.para(self.pick(RISK, 5))
        b.line("6. 주요계약 및 연구개발활동")
        b.para(self.pick(RND, 5))
        b.line("7. 기타 참고사항")
        b.para(self.pick(MARKET, 3) + self.pick(RISK, 2))

    def summary_table(self, b: Builder, basis: str, year: int, values: dict, years: list[int], fact_ok: bool) -> None:
        s = self.s
        title = "가. 요약연결재무정보" if basis == "연결" else "나. 요약별도재무정보"
        b.line(title)
        b.line("(단위: 백만원)")
        b.line("구 분 | " + " | ".join(f"제 {s.fiscal_no(y)} 기 ({y}년)" for y in years))
        rows = [("[유동자산]", "유동자산"), ("[비유동자산]", "비유동자산"), ("자산총계", "자산총계"),
                ("[유동부채]", "유동부채"), ("[비유동부채]", "비유동부채"), ("부채총계", "부채총계"),
                ("[자본금]", "자본금"), ("[이익잉여금]", "이익잉여금"), ("자본총계", "자본총계"),
                ("매출액", "매출액"), ("영업이익(손실)", "영업이익"), ("당기순이익(손실)", "당기순이익")]
        for label, line in rows:
            b.row(label, [values[y][line] for y in years], "백만원",
                  [(s.key, basis, line, f"FY{y}") if fact_ok else None for y in years])
        if basis == "연결":
            b.line("연결에 포함된 회사수 | " + " | ".join(str(self.rng.randint(2, 14)) for _ in years))
        b.line()

    def statements(self, b: Builder, basis: str, year: int, values: dict, fact_ok: bool) -> None:
        s = self.s
        prefix = "연결 " if basis == "연결" else ""
        cols = [year, year - 1] if year - 1 in values else [year]
        b.line(f"{prefix}재무상태표")
        b.line(" | ".join(f"제 {s.fiscal_no(y)} 기 {y}.12.31 현재" for y in cols))
        b.line("(단위: 백만원)")
        b.line("과 목 | " + " | ".join(f"제 {s.fiscal_no(y)} 기" for y in cols))
        for line in BS_LINES:
            b.row(line, [values[y][line] for y in cols], "백만원",
                  [(s.key, basis, line, f"FY{y}") if fact_ok else None for y in cols])
        b.line()
        b.line(f"{prefix}포괄손익계산서")
        b.line(" | ".join(f"제 {s.fiscal_no(y)} 기 {y}.01.01 부터 {y}.12.31 까지" for y in cols))
        b.line("(단위: 백만원)")
        b.line("과 목 | " + " | ".join(f"제 {s.fiscal_no(y)} 기" for y in cols))
        for line in IS_LINES:
            label = {"영업이익": "영업이익(손실)", "당기순이익": "당기순이익(손실)"}.get(line, line)
            b.row(label, [values[y][line] for y in cols], "백만원",
                  [(s.key, basis, line, f"FY{y}") if fact_ok else None for y in cols])
        b.line()

    def note_tables(self, b: Builder, basis: str, year: int, values: dict, unit: str = "백만원", div: int = 1) -> None:
        """Note tables full of look-alike numbers. The SG&A breakdown and the tax note sum to the
        income-statement lines, as in real filings."""
        r = self.rng
        cur = values[year]
        rev = max(cur["매출액"], 1)
        b.line("가. 재고자산의 내역")
        b.line(f"(단위: {unit})")
        b.line("구 분 | 취득원가 | 평가충당금 | 장부금액")
        for item in ("제품", "상품", "재공품", "원재료", "저장품"):
            cost = int(rev * r.uniform(0.005, 0.06)) // div
            allow = int(cost * r.uniform(0.0, 0.08))
            b.row(item, [cost, -allow, cost - allow], unit, [None, None, None])
        b.line()
        b.line("나. 판매비와관리비의 내역")
        b.line(f"(단위: {unit})")
        b.line(f"구 분 | 당기 | 전기")
        prev = values.get(year - 1, cur)
        items = ["급여", "퇴직급여", "복리후생비", "감가상각비", "지급수수료", "광고선전비", "운반비", "경상연구개발비", "기타"]
        def parts(total: int) -> list[int]:
            w = [r.uniform(0.3, 1.0) for _ in items]
            sw = sum(w)
            ps = [int(total * x / sw) for x in w[:-1]]
            return ps + [total - sum(ps)]
        pc, pp = parts(cur["판매비와관리비"] // div), parts(prev["판매비와관리비"] // div)
        for item, a, c in zip(items, pc, pp):
            b.row(item, [a, c], unit, [None, None])
        b.row("합 계", [sum(pc), sum(pp)], unit, [None, None])
        b.line()
        b.line("다. 차입금의 내역")
        b.line(f"(단위: {unit})")
        b.line("구 분 | 차입처 | 연이자율(%) | 당기말 | 전기말")
        for item in ("단기차입금", "유동성장기차입금", "장기차입금", "사채"):
            lender = r.choice(["한결은행", "누리은행", "가온캐피탈", "공모"])
            amt = int(rev * r.uniform(0.0, 0.12)) // div
            b.line(f"{item} | {lender} | {r.uniform(2.8, 6.4):.2f} | {amt:,} | {int(amt * r.uniform(0.7, 1.3)):,}")
        b.line()
        b.line("라. 법인세비용의 구성내역")
        b.line(f"(단위: {unit})")
        tax = cur["법인세비용"] // div
        deferred = int(tax * r.uniform(-0.3, 0.3))
        b.row("당기법인세부담액", [tax - deferred], unit, [None])
        b.row("일시적차이로 인한 이연법인세 변동액", [deferred], unit, [None])
        b.row("법인세비용", [tax], unit, [None])
        b.line()
        b.para(self.pick(NOTES, 3))

    def mdna(self, b: Builder, year: int, values: dict) -> None:
        cur, prev = values[year], values.get(year - 1)
        r = self.rng
        b.line("IV. 이사의 경영진단 및 분석의견")
        sent = [f"당기 연결 매출액은 {eok_text(cur['매출액'])}으로"]
        if prev:
            g = (cur["매출액"] / prev["매출액"] - 1) * 100
            sent[0] += f" 전기 대비 {abs(g):.1f}% {'증가' if g >= 0 else '감소'}하였습니다."
        else:
            sent[0] += " 집계되었습니다."
        op = cur["영업이익"]
        sent.append(f"영업{'이익' if op >= 0 else '손실'}은 {eok_text(abs(op))}을 기록하였으며, 이는 {self.rng.choice(['판가 개선', '제품 믹스 개선', '원가 부담 확대', '고정비 증가', '환율 효과'])}에 기인합니다.")
        sent += self.pick(MARKET, 2) + self.pick(RISK, 2)
        sent.append(f"차기에는 {r.choice(self.s.products)} 신제품 출시와 {r.choice(REGIONS)} 시장 확대를 통해 외형 성장을 추진할 계획입니다.")
        b.para(sent)

    def tail_sections(self, b: Builder, year: int, short: bool = False) -> None:
        r, s, fin = self.rng, self.s, self.fin
        b.line("V. 회계감사인의 감사의견 등")
        b.para(self.pick(AUDIT, 2 if short else 4))
        b.line("VI. 이사회 등 회사의 기관에 관한 사항")
        b.para(self.pick(GOV, 2 if short else 5))
        if short:
            b.line("VII. 주주에 관한 사항 ~ XI. 그 밖에 투자자 보호를 위하여 필요한 사항")
            b.para(["분기·반기보고서에는 기재를 생략하거나 변동사항만 기재합니다."])
            return
        b.line("VII. 주주에 관한 사항")
        b.para([f"최대주주는 {s.ceo} 외 특수관계인 {r.randint(2, 9)}인이며, 보유 지분율은 {r.uniform(18, 55):.2f}%입니다.",
                f"5% 이상 주주로는 국민연금공단({r.uniform(5, 11):.2f}%)이 있습니다."])
        b.line("VIII. 임원 및 직원 등에 관한 사항")
        b.para([f"보고서 작성기준일 현재 직원 수는 {fin.employees.get(year, 500):,}명이며, 평균 근속연수는 {r.uniform(4, 16):.1f}년입니다.",
                f"1인 평균 급여액은 {r.randint(48, 128)}백만원입니다.",
                f"등기임원은 {r.randint(5, 11)}명이며, 미등기임원은 {r.randint(3, 30)}명입니다."])
        b.line("IX. 계열회사 등에 관한 사항")
        b.para([f"당사가 속한 기업집단의 계열회사는 총 {r.randint(3, 25)}개사입니다(상장 {r.randint(1, 3)}개사)."])
        b.line("X. 대주주 등과의 거래내용")
        b.para([f"당기 중 특수관계자에 대한 매출 등 거래 총액은 {r.randint(100, 90_000):,}백만원입니다."])
        b.line("XI. 그 밖에 투자자 보호를 위하여 필요한 사항")
        b.para([f"당기 중 제재 현황은 없으며, 진행 중인 소송은 {r.randint(0, 6)}건입니다.",
                "작성기준일 이후 발생한 주요 사항은 없습니다."])

    # -- documents
    def annual_report(self, doc: Document, year: int, values_con: dict, values_sep: dict,
                      fact_ok: bool = True, correction_header: list | None = None) -> None:
        s, fin = self.s, self.fin
        b = Builder(doc)
        if correction_header:
            b.lines(correction_header)
        self.cover(b, "사 업 보 고 서", f"사업연도 {year}년 01월 01일 부터 {year}년 12월 31일 까지",
                   f"제 {s.fiscal_no(year)} 기")
        self.overview(b, year)
        self.business(b, year)
        years = [y for y in (year, year - 1, year - 2) if y in values_con]
        b.line("III. 재무에 관한 사항")
        b.line("1. 요약재무정보")
        self.summary_table(b, "연결", year, values_con, years, fact_ok)
        self.summary_table(b, "별도", year, values_sep, years, fact_ok)
        b.line("2. 연결재무제표")
        self.statements(b, "연결", year, values_con, fact_ok)
        b.line("3. 연결재무제표 주석")
        b.para(self.pick(NOTES, 6))
        self.note_tables(b, "연결", year, values_con)
        b.line("4. 재무제표")
        self.statements(b, "별도", year, values_sep, fact_ok)
        b.line("5. 재무제표 주석")
        b.para(self.pick(NOTES, 4))
        self.note_tables(b, "별도", year, values_sep)
        b.line("6. 배당에 관한 사항")
        b.para([f"당기 주당 현금배당금은 {fin.dps[year]:,}원이며, 전기 주당 배당금은 {fin.dps.get(year - 1, 0):,}원입니다."])
        self.mdna(b, year, values_con)
        self.tail_sections(b, year)
        doc.text = b.text()

    def quarterly_report(self, doc: Document, q: int) -> None:
        """2026 1분기 (q=1) or 반기 (q=2) report."""
        s, fin, r = self.s, self.fin, self.rng
        unit = s.quarterly_unit
        div = 1 if unit == "천원" else 1000
        b = Builder(doc)
        title = "분 기 보 고 서" if q == 1 else "반 기 보 고 서"
        end = "03월 31일" if q == 1 else "06월 30일"
        label = "1분기" if q == 1 else "반기"
        self.cover(b, title, f"사업연도 2026년 01월 01일 부터 2026년 12월 31일 까지 (보고기간 2026년 01월 01일 ~ 2026년 {end})",
                   f"제 {s.fiscal_no(2026)} 기 {label}")
        self.overview(b, 2025, short=True)
        self.business(b, 2025, short=True)
        b.line("III. 재무에 관한 사항")
        for basis, head in (("연결", "2. 연결재무제표"), ("별도", "4. 재무제표")):
            if basis == "별도":
                b.line("3. 연결재무제표 주석")
                b.para(self.pick(NOTES, 3))
            b.line(head)
            prefix = "연결 " if basis == "연결" else ""
            ye = fin.annual[(basis, 2025)]
            bs_now = {k: int(round(v * 1000 * r.uniform(0.97, 1.06))) + r.randint(0, 999) for k, v in ye.items() if k in BS_LINES}
            b.line(f"{prefix}재무상태표")
            b.line(f"제 {s.fiscal_no(2026)} 기 {label}말 2026.{'03.31' if q == 1 else '06.30'} 현재 | 제 {s.fiscal_no(2025)} 기말 2025.12.31 현재")
            b.line(f"(단위: {unit})")
            b.line(f"과 목 | 제 {s.fiscal_no(2026)} 기 {label}말 | 제 {s.fiscal_no(2025)} 기말")
            for line in BS_LINES:
                b.row(line, [bs_now[line] // div, ye[line] * 1000 // div], unit, [None, None])
            b.line()
            b.line(f"{prefix}포괄손익계산서")
            cur = {k: fin.quarters[(basis, 2026, q)][k] for k in IS_LINES}
            prev = {k: fin.quarters[(basis, 2025, q)][k] for k in IS_LINES}
            if q == 1:
                b.line(f"제 {s.fiscal_no(2026)} 기 1분기 2026.01.01 부터 2026.03.31 까지 | 제 {s.fiscal_no(2025)} 기 1분기 2025.01.01 부터 2025.03.31 까지")
                b.line(f"(단위: {unit})")
                b.line(f"과 목 | 제 {s.fiscal_no(2026)} 기 1분기 | 제 {s.fiscal_no(2025)} 기 1분기")
                for line in IS_LINES:
                    lab = {"영업이익": "영업이익(손실)", "당기순이익": "당기순이익(손실)"}.get(line, line)
                    b.row(lab, [cur[line] // div, prev[line] // div], unit,
                          [(s.key, basis, line, "2026Q1"), (s.key, basis, line, "2025Q1")])
            else:
                cum = {k: fin.quarters[(basis, 2026, 1)][k] + cur[k] for k in IS_LINES}
                pcum = {k: fin.quarters[(basis, 2025, 1)][k] + prev[k] for k in IS_LINES}
                b.line(f"제 {s.fiscal_no(2026)} 기 반기 2026.01.01 부터 2026.06.30 까지 | 제 {s.fiscal_no(2025)} 기 반기 2025.01.01 부터 2025.06.30 까지")
                b.line(f"(단위: {unit})")
                b.line(f"과 목 | 제 {s.fiscal_no(2026)} 기 반기 3개월 | 제 {s.fiscal_no(2026)} 기 반기 누적 | "
                       f"제 {s.fiscal_no(2025)} 기 반기 3개월 | 제 {s.fiscal_no(2025)} 기 반기 누적")
                for line in IS_LINES:
                    lab = {"영업이익": "영업이익(손실)", "당기순이익": "당기순이익(손실)"}.get(line, line)
                    b.row(lab, [cur[line] // div, cum[line] // div, prev[line] // div, pcum[line] // div], unit,
                          [(s.key, basis, line, "2026Q2_3M"), (s.key, basis, line, "2026H1_CUM"),
                           (s.key, basis, line, "2025Q2_3M"), (s.key, basis, line, "2025H1_CUM")])
            b.line()
        b.line("5. 재무제표 주석")
        b.para(self.pick(NOTES, 3))
        b.line("IV. 이사의 경영진단 및 분석의견")
        b.para(["분기·반기보고서에는 기재하지 않습니다(사업보고서에 기재)."])
        self.tail_sections(b, 2026, short=True)
        doc.text = b.text()

    def preliminary_report(self, doc: Document) -> None:
        s, fin = self.s, self.fin
        p = fin.preliminary
        prev = fin.annual[("연결", 2024)]
        b = Builder(doc)
        b.lines(["연결재무제표기준영업(잠정)실적(공정공시)", NOTICE, "", f"회사명: {s.name}", f"종목코드: {s.code}",
                 f"접수번호: {doc.rcept_no}", f"제출일: {doc.filed}", "",
                 "※ 동 정보는 잠정치로서 향후 확정치와는 다를 수 있음", "",
                 "1. 연결실적내용", "(단위: 억원, %)",
                 "구분 | 당기실적 (2025년) | 전기실적 (2024년) | 전기대비증감율(%)"])
        for line in ("매출액", "영업이익", "법인세비용차감전순이익", "당기순이익"):
            prev_eok = int(round(prev[line] / 100))
            chg = (p[line] / prev_eok - 1) * 100 if prev_eok else 0.0
            label = {"매출액": "매출액", "영업이익": "영업이익", "법인세비용차감전순이익": "법인세비용차감전계속사업이익",
                     "당기순이익": "당기순이익"}[line]
            b.row(label, [p[line], prev_eok], "억원", [(s.key, "연결", line, "FY2025"), None])
            b.parts[-1] = b.parts[-1].rstrip("\n") + f" | {chg:.1f}\n"
            b.n += len(f" | {chg:.1f}")
        b.lines(["", "2. 정보제공내역",
                 f"정보제공자: IR팀 | 정보제공대상자: 국내외 투자자 및 애널리스트 | 정보제공(예정)일시: {doc.filed}",
                 "3. 연락처(관련부서/전화번호): IR팀",
                 "4. 기타 투자판단과 관련한 중요사항",
                 "- 상기 실적은 외부감사인의 감사가 완료되지 않은 잠정 수치로, 감사 결과에 따라 변동될 수 있습니다.",
                 "- 확정 실적은 사업보고서를 통해 공시할 예정입니다."])
        doc.text = b.text()

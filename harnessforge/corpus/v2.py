"""v2 benchmark corpus: 30 fictional companies, more filing types and more traps.

New relative to v1 (v1 stays byte-identical; see tests/test_v2.py):

* Filing types: 3분기보고서 (2025.09), 감사보고서 (FY2025), 상호변경 공시, and a [기재정정] of a 잠정실적
  disclosure, besides annual, Q1, half-year, [기재정정] annual and 잠정실적 filings.
* Traps: prior-year figures restated in the next annual report (재작성), a company renamed mid-2025
  whose older filings carry the old name, annual statements printed in 천원 in one year and 백만원 in
  the others, and a corrected preliminary disclosure that is still not final.
* Companies are split three ways (search / validation / test) so a rule chosen on validation is
  never scored on the same questions.

Every document carries the same synthetic-data notice as v1.
"""

from __future__ import annotations

import dataclasses
import hashlib
import random
from dataclasses import asdict, dataclass

from .finance import BS_LINES, IS_LINES, CompanySpec, CompanyFinancials, _close_is, _quarter_lines, generate_financials, split_total
from .render import AUDIT, GOV, NOTES, NOTICE, Builder, Document, Renderer, eok_text, fmt

# key, name, sector, segments, products, ceo, city, founded
COMPANIES_V2 = [
    ("ara_semicon", "아라반도체", "반도체 장비", ["식각장비", "세정장비"], ["건식 식각기", "매엽식 세정기"], "강민호", "경기도 평택시", 2003),
    ("ara_semitech", "아라세미텍", "반도체 소재", ["전구체", "특수가스"], ["고유전 전구체", "식각 가스"], "김지안", "충청남도 천안시", 2010),
    ("dongbang_const", "동방건설", "건설", ["주택", "토목"], ["공동주택", "도로"], "박정우", "서울특별시 강남구", 1981),
    ("dongbang_const_ind", "동방건설산업", "건설자재", ["레미콘", "철근가공"], ["레미콘", "가공철근"], "이서진", "경기도 화성시", 1994),
    ("hangyeol_pharm", "한결제약", "제약", ["전문의약품", "원료의약품"], ["고지혈증 치료제", "원료 API"], "최윤서", "경기도 안산시", 1975),
    ("hangyeol_pharmbio", "한결제약바이오", "바이오", ["항체의약품", "위탁개발생산"], ["항체 바이오시밀러", "CDMO 서비스"], "정하준", "인천광역시 연수구", 2014),
    ("sorae_chem", "소래화학", "정밀화학", ["도료", "접착제", "특수수지"], ["산업용 도료", "구조용 접착제"], "윤도윤", "경기도 시흥시", 1988),
    ("bitnara_display", "빛나라디스플레이", "디스플레이 소재", ["OLED 소재", "편광필름"], ["발광 소재", "편광판"], "장예린", "충청남도 아산시", 2005),
    ("gaon_ship", "가온조선", "조선", ["상선", "특수선"], ["LNG 운반선", "해양 순찰선"], "임재원", "경상남도 거제시", 1979),
    ("haneul_air", "하늘항공", "항공운송", ["여객", "화물"], ["국제선 여객", "항공 화물"], "한소율", "서울특별시 강서구", 1996),
    ("purun_food", "푸른식품", "식품", ["육가공", "간편식", "음료"], ["햄·소시지", "냉동 간편식"], "오시우", "충청북도 음성군", 1983),
    ("seowon_textile", "서원섬유", "섬유", ["원사", "원단"], ["폴리에스터 원사", "기능성 원단"], "서지호", "경상북도 구미시", 1972),
    ("robowon", "로보원", "로봇", ["협동로봇", "물류로봇"], ["6축 협동로봇", "자율주행 운반로봇"], "권다은", "경기도 성남시", 2012),
    ("onsaemi_ent", "온새미엔터", "엔터테인먼트", ["음반", "공연", "IP"], ["정규 음반", "월드 투어"], "황시윤", "서울특별시 성동구", 2008),
    ("haeoreum_energy", "해오름에너지", "신재생에너지", ["풍력", "ESS"], ["해상풍력 타워", "에너지저장장치"], "문지율", "전라남도 영광군", 2006),
    ("sanha_cosmetics", "산하코스메틱", "화장품", ["스킨케어", "색조"], ["기초 화장품", "쿠션 파운데이션"], "배수아", "경기도 오산시", 2001),
    ("geumbit_steel", "금빛제강", "철강", ["봉형강", "강판"], ["철근", "열연강판"], "신우진", "경상북도 포항시", 1977),
    ("chorok_paper", "초록제지", "제지", ["인쇄용지", "산업용지"], ["백상지", "골판지 원지"], "유채원", "전라북도 전주시", 1969),
    ("baram_auto", "바람오토텍", "자동차부품", ["차체부품", "내장재"], ["도어 모듈", "시트 프레임"], "남궁현", "울산광역시 북구", 1990),
    ("narae_telecom", "나래텔레콤", "통신서비스", ["무선", "유선", "IDC"], ["5G 요금제", "기업 회선"], "고은호", "서울특별시 중구", 1998),
    ("hanseol_software", "한설소프트", "소프트웨어", ["ERP", "보안"], ["클라우드 ERP", "엔드포인트 보안"], "백지성", "경기도 성남시", 2000),
    ("dasom_medical", "다솜메디칼", "의료기기", ["영상진단", "체외진단"], ["초음파 진단기", "면역진단 키트"], "송하린", "강원특별자치도 원주시", 2004),
    ("gangsan_cement", "강산시멘트", "시멘트", ["시멘트", "레미콘"], ["포틀랜드 시멘트", "고강도 레미콘"], "노태현", "충청북도 단양군", 1965),
    ("yeoul_retail", "여울리테일", "유통", ["편의점", "온라인"], ["가맹 편의점", "온라인 장보기"], "하은채", "서울특별시 송파구", 1993),
    ("sejin_shipping", "세진해운", "해운", ["컨테이너", "벌크"], ["컨테이너 정기선", "벌크선 용선"], "구민혁", "부산광역시 중구", 1985),
    ("onyu_battery", "온유배터리", "이차전지", ["셀", "모듈"], ["파우치형 셀", "ESS 모듈"], "차윤아", "충청북도 청주시", 2011),
    ("pyeonghwa_machine", "평화기공", "기계", ["공작기계", "유압기기"], ["CNC 선반", "유압 실린더"], "엄도현", "경상남도 창원시", 1976),
    ("joeun_bio", "조은바이오", "바이오", ["백신", "진단"], ["독감 백신", "분자진단 키트"], "진서윤", "대전광역시 유성구", 2009),
    ("hamo_fashion", "하모패션", "의류", ["캐주얼", "아웃도어"], ["데님 캐주얼", "등산복"], "석지안", "서울특별시 마포구", 1997),
    ("seorin_data", "서린데이터", "IT서비스", ["클라우드", "AI 솔루션"], ["관리형 클라우드", "문서 AI"], "탁준서", "서울특별시 구로구", 1999),
]
SPLITS = {
    "search": {"sorae_chem", "gaon_ship", "purun_food", "seowon_textile", "sanha_cosmetics", "chorok_paper",
               "dongbang_const_ind", "hangyeol_pharmbio"},
    "validation": {"haneul_air", "geumbit_steel", "narae_telecom", "gangsan_cement", "seorin_data", "sejin_shipping"},
}
CORRECTION = {"sorae_chem", "chorok_paper", "geumbit_steel", "ara_semicon", "hangyeol_pharm", "onyu_battery",
              "hanseol_software", "joeun_bio"}
PRELIMINARY = {"purun_food", "sanha_cosmetics", "narae_telecom", "gangsan_cement", "ara_semicon", "bitnara_display",
               "haeoreum_energy", "yeoul_retail", "pyeonghwa_machine", "hamo_fashion"}
PRELIM_CORRECTED = {"sanha_cosmetics", "gangsan_cement", "bitnara_display", "yeoul_retail"}
QUARTER_THOUSAND = {"gaon_ship", "seowon_textile", "dongbang_const_ind", "haneul_air", "sejin_shipping", "ara_semitech",
                    "robowon", "onsaemi_ent", "dasom_medical", "hamo_fashion"}
ANNUAL_THOUSAND = {"gaon_ship", "sejin_shipping", "dongbang_const", "dasom_medical", "onyu_battery", "joeun_bio"}
RESTATED = {"purun_food", "haneul_air", "bitnara_display", "robowon", "hanseol_software", "pyeonghwa_machine"}
RENAMED = {"seorin_data": "서린정보통신", "baram_auto": "바람정공"}
NOTICE_RENAME = "상호변경"


@dataclass
class CompanySpecV2(CompanySpec):
    annual_unit: str = "백만원"     # unit of the FY2025 annual report and audit report statements
    restated: bool = False          # the FY2025 report restates the FY2024 comparatives
    old_name: str | None = None     # renamed in mid-2025; earlier filings carry this name
    prelim_corrected: bool = False  # the 잠정실적 disclosure has its own [기재정정]


def company_specs_v2() -> list[CompanySpecV2]:
    out = []
    for i, (key, name, sector, segs, prods, ceo, city, founded) in enumerate(COMPANIES_V2):
        split = next((s for s, keys in SPLITS.items() if key in keys), "test")
        out.append(CompanySpecV2(
            key=key, name=name, code=f"98{(i + 1) * 10:03d}0"[:6], sector=sector, segments=segs, products=prods,
            ceo=ceo, city=city, founded=founded, correction=key in CORRECTION, preliminary=key in PRELIMINARY,
            quarterly_unit="천원" if key in QUARTER_THOUSAND else "백만원", split=split,
            annual_unit="천원" if key in ANNUAL_THOUSAND else "백만원", restated=key in RESTATED,
            old_name=RENAMED.get(key), prelim_corrected=key in PRELIM_CORRECTED))
    return out


def extend_financials(fin: CompanyFinancials, rng: random.Random) -> None:
    """v2 additions on top of the v1 generator: 2024 quarters, a restated FY2024, a corrected
    preliminary disclosure, and the 2022 dividend."""
    s = fin.spec
    fin.dps.setdefault(2022, rng.choice([0, 100, 150, 200, 250, 300, 400, 500]))
    for basis in ("연결", "별도"):
        annual = fin.annual[(basis, 2024)]
        shares = split_total(1000, 4, rng, low=0.7)
        parts = {q: _quarter_lines(annual, annual["매출액"] * shares[q - 1], rng) for q in (1, 2, 3)}
        parts[4] = {k: annual[k] * 1000 - sum(parts[q][k] for q in (1, 2, 3)) for k in IS_LINES}
        for q in (1, 2, 3, 4):
            fin.quarters[(basis, 2024, q)] = parts[q]
    fin.restated = {}
    fin.restated_segments = {}
    if s.restated:
        orig = fin.annual[("연결", 2024)]
        f = 1 + rng.choice([-1, 1]) * rng.uniform(0.03, 0.08)
        lines = {k: int(round(orig[k] * f)) for k in ("매출액", "매출원가", "판매비와관리비", "금융수익", "금융비용", "기타수익", "기타비용")}
        lines["매출총이익"] = lines["매출액"] - lines["매출원가"]
        lines["영업이익"] = lines["매출총이익"] - lines["판매비와관리비"]
        fin.restated[("연결", 2024)] = _close_is(lines, orig.get("_tax_rate", 0.22)) | {k: orig[k] for k in BS_LINES}
        segs = fin.segments[2024]
        scaled = {k: int(round(v * f)) for k, v in segs.items()}
        last = list(scaled)[-1]
        scaled[last] = lines["매출액"] - sum(v for k, v in scaled.items() if k != last)
        fin.restated_segments[2024] = scaled
    fin.prelim_corrected = {}
    if s.prelim_corrected and fin.preliminary:
        fin.prelim_corrected = {k: int(round(v * (1 + rng.choice([-1, 1]) * rng.uniform(0.01, 0.03))))
                                for k, v in fin.preliminary.items()}


class RendererV2(Renderer):
    """Adds units other than 백만원, restated comparatives, dividend facts and the new filing types."""

    unit = "백만원"

    # -- unit-aware copies of the v1 tables (v1 hard-codes 백만원)
    def summary_table(self, b: Builder, basis: str, year: int, values: dict, years: list[int], fact_ok: bool) -> None:
        s = self.s
        b.line("가. 요약연결재무정보" if basis == "연결" else "나. 요약별도재무정보")
        b.line(f"(단위: {self.unit})")
        b.line("구 분 | " + " | ".join(f"제 {s.fiscal_no(y)} 기 ({y}년)" for y in years))
        rows = [("[유동자산]", "유동자산"), ("[비유동자산]", "비유동자산"), ("자산총계", "자산총계"),
                ("[유동부채]", "유동부채"), ("[비유동부채]", "비유동부채"), ("부채총계", "부채총계"),
                ("[자본금]", "자본금"), ("[이익잉여금]", "이익잉여금"), ("자본총계", "자본총계"),
                ("매출액", "매출액"), ("영업이익(손실)", "영업이익"), ("당기순이익(손실)", "당기순이익")]
        for label, line in rows:
            b.row(label, [values[y][line] for y in years], self.unit,
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
        b.line(f"(단위: {self.unit})")
        b.line("과 목 | " + " | ".join(f"제 {s.fiscal_no(y)} 기" for y in cols))
        for line in BS_LINES:
            b.row(line, [values[y][line] for y in cols], self.unit,
                  [(s.key, basis, line, f"FY{y}") if fact_ok else None for y in cols])
        b.line()
        b.line(f"{prefix}포괄손익계산서")
        b.line(" | ".join(f"제 {s.fiscal_no(y)} 기 {y}.01.01 부터 {y}.12.31 까지" for y in cols))
        b.line(f"(단위: {self.unit})")
        b.line("과 목 | " + " | ".join(f"제 {s.fiscal_no(y)} 기" for y in cols))
        for line in IS_LINES:
            label = {"영업이익": "영업이익(손실)", "당기순이익": "당기순이익(손실)"}.get(line, line)
            b.row(label, [values[y][line] for y in cols], self.unit,
                  [(s.key, basis, line, f"FY{y}") if fact_ok else None for y in cols])
        b.line()

    def dividend_line(self, b: Builder, year: int) -> None:
        cur, prev = self.fin.dps.get(year, 0), self.fin.dps.get(year - 1, 0)
        pre, mid, post = "당기 주당 현금배당금은 ", "원이며, 전기 주당 배당금은 ", "원입니다."
        s1, s2 = f"{cur:,}", f"{prev:,}"
        start = b.n
        o1 = start + len(pre)
        o2 = o1 + len(s1) + len(mid)
        for off, v, y in ((o1, cur, year), (o2, prev, year - 1)):
            b.doc.facts.append(_fact(b.doc, (self.s.key, "연결", "주당배당금", f"FY{y}"), off, start, v, "원"))
        b.line(pre + s1 + mid + s2 + post)
        b.line()

    @staticmethod
    def scaled(values: dict, mult: int) -> dict:
        return {y: {k: (v * mult if isinstance(v, int) else v) for k, v in lines.items()} for y, lines in values.items()}

    # -- documents
    def annual_report_v2(self, doc: Document, year: int, values_con: dict, values_sep: dict, unit: str,
                         restated_note: bool = False, correction_header: list | None = None) -> None:
        s, fin = self.s, self.fin
        mult = 1000 if unit == "천원" else 1
        self.unit = unit
        con_u, sep_u = self.scaled(values_con, mult), self.scaled(values_sep, mult)
        b = Builder(doc)
        if correction_header:
            b.lines(correction_header)
        self.cover(b, "사 업 보 고 서", f"사업연도 {year}년 01월 01일 부터 {year}년 12월 31일 까지", f"제 {s.fiscal_no(year)} 기")
        self.overview(b, year)
        swapped = None
        if restated_note and year - 1 in fin.restated_segments:
            swapped = fin.segments[year - 1]
            fin.segments[year - 1] = fin.restated_segments[year - 1]
        self.business(b, year)
        if swapped is not None:
            fin.segments[year - 1] = swapped
        years = [y for y in (year, year - 1, year - 2) if y in values_con]
        b.line("III. 재무에 관한 사항")
        if restated_note:
            b.para([f"※ 제 {s.fiscal_no(year - 1)} 기(전기) 연결재무제표는 회계정책 변경에 따라 재작성되었으며, "
                    "아래 전기 수치는 재작성 후 금액입니다. 직전 사업보고서의 수치와 다를 수 있습니다."])
        b.line("1. 요약재무정보")
        self.summary_table(b, "연결", year, con_u, years, True)
        self.summary_table(b, "별도", year, sep_u, years, True)
        b.line("2. 연결재무제표")
        self.statements(b, "연결", year, con_u, True)
        b.line("3. 연결재무제표 주석")
        b.para(self.pick(NOTES, 6))
        self.note_tables(b, "연결", year, con_u, unit=unit)
        b.line("4. 재무제표")
        self.statements(b, "별도", year, sep_u, True)
        b.line("5. 재무제표 주석")
        b.para(self.pick(NOTES, 4))
        self.note_tables(b, "별도", year, sep_u, unit=unit)
        b.line("6. 배당에 관한 사항")
        self.dividend_line(b, year)
        self.mdna(b, year, values_con)
        self.tail_sections(b, year)
        doc.text = b.text()
        self.unit = "백만원"

    def audit_report(self, doc: Document, year: int, values_con: dict, values_sep: dict, unit: str) -> None:
        s = self.s
        mult = 1000 if unit == "천원" else 1
        self.unit = unit
        b = Builder(doc)
        b.lines(["감 사 보 고 서", NOTICE, "", f"{doc.company} 주주 및 이사회 귀중", "",
                 "독립된 감사인의 감사보고서"])
        b.para([f"우리는 {doc.company}와 그 종속기업의 연결재무제표와 {doc.company}의 별도재무제표를 감사하였습니다.",
                f"우리의 의견으로는 회사의 재무제표는 {year}년 12월 31일 현재의 재무상태와 같은 날로 종료되는 보고기간의 "
                "재무성과를 한국채택국제회계기준에 따라 중요성의 관점에서 공정하게 표시하고 있습니다."] + self.pick(AUDIT, 2))
        b.line("(첨부) 연결재무제표")
        self.statements(b, "연결", year, self.scaled(values_con, mult), True)
        b.line("(첨부) 별도재무제표")
        self.statements(b, "별도", year, self.scaled(values_sep, mult), True)
        b.line("주석")
        b.para(self.pick(NOTES, 5))
        doc.text = b.text()
        self.unit = "백만원"

    def quarterly_report_v2(self, doc: Document, year: int, q: int) -> None:
        """Q1 / half-year / Q3 report with 3-month and cumulative columns against the prior year."""
        s, fin, r = self.s, self.fin, self.rng
        unit = s.quarterly_unit
        div = 1 if unit == "천원" else 1000
        b = Builder(doc)
        title = {1: "분 기 보 고 서", 2: "반 기 보 고 서", 3: "분 기 보 고 서"}[q]
        label = {1: "1분기", 2: "반기", 3: "3분기"}[q]
        end = {1: "03.31", 2: "06.30", 3: "09.30"}[q]
        self.cover(b, title, f"사업연도 {year}년 01월 01일 부터 {year}년 12월 31일 까지 (보고기간 {year}.01.01 ~ {year}.{end})",
                   f"제 {s.fiscal_no(year)} 기 {label}")
        self.overview(b, year - 1, short=True)
        self.business(b, year - 1, short=True)
        b.line("III. 재무에 관한 사항")
        for basis, head in (("연결", "2. 연결재무제표"), ("별도", "4. 재무제표")):
            if basis == "별도":
                b.line("3. 연결재무제표 주석")
                b.para(self.pick(NOTES, 3))
            b.line(head)
            prefix = "연결 " if basis == "연결" else ""
            ye = fin.annual[(basis, year - 1)]
            bs_now = {k: int(round(v * 1000 * r.uniform(0.97, 1.06))) + r.randint(0, 999) for k, v in ye.items() if k in BS_LINES}
            b.line(f"{prefix}재무상태표")
            b.line(f"(단위: {unit})")
            b.line(f"과 목 | 제 {s.fiscal_no(year)} 기 {label}말 | 제 {s.fiscal_no(year - 1)} 기말")
            for line in BS_LINES:
                b.row(line, [bs_now[line] // div, ye[line] * 1000 // div], unit, [None, None])
            b.line()
            b.line(f"{prefix}포괄손익계산서")
            b.line(f"(단위: {unit})")
            cur = {k: fin.quarters[(basis, year, q)][k] for k in IS_LINES}
            prev = {k: fin.quarters[(basis, year - 1, q)][k] for k in IS_LINES}
            if q == 1:
                b.line(f"과 목 | 제 {s.fiscal_no(year)} 기 1분기 | 제 {s.fiscal_no(year - 1)} 기 1분기")
                for line in IS_LINES:
                    lab = {"영업이익": "영업이익(손실)", "당기순이익": "당기순이익(손실)"}.get(line, line)
                    b.row(lab, [cur[line] // div, prev[line] // div], unit,
                          [(s.key, basis, line, f"{year}Q1"), (s.key, basis, line, f"{year - 1}Q1")])
            else:
                cum = {k: sum(fin.quarters[(basis, year, i)][k] for i in range(1, q + 1)) for k in IS_LINES}
                pcum = {k: sum(fin.quarters[(basis, year - 1, i)][k] for i in range(1, q + 1)) for k in IS_LINES}
                tag3 = "Q2_3M" if q == 2 else "Q3_3M"
                tagc = "H1_CUM" if q == 2 else "Q3_CUM"
                b.line(f"과 목 | 제 {s.fiscal_no(year)} 기 {label} 3개월 | 제 {s.fiscal_no(year)} 기 {label} 누적 | "
                       f"제 {s.fiscal_no(year - 1)} 기 {label} 3개월 | 제 {s.fiscal_no(year - 1)} 기 {label} 누적")
                for line in IS_LINES:
                    lab = {"영업이익": "영업이익(손실)", "당기순이익": "당기순이익(손실)"}.get(line, line)
                    b.row(lab, [cur[line] // div, cum[line] // div, prev[line] // div, pcum[line] // div], unit,
                          [(s.key, basis, line, f"{year}{tag3}"), (s.key, basis, line, f"{year}{tagc}"),
                           (s.key, basis, line, f"{year - 1}{tag3}"), (s.key, basis, line, f"{year - 1}{tagc}")])
            b.line()
        b.line("5. 재무제표 주석")
        b.para(self.pick(NOTES, 3))
        b.line("IV. 이사의 경영진단 및 분석의견")
        b.para(["분기·반기보고서에는 기재하지 않습니다(사업보고서에 기재)."])
        self.tail_sections(b, year, short=True)
        doc.text = b.text()

    def rename_notice(self, doc: Document) -> None:
        s = self.s
        b = Builder(doc)
        b.lines(["주요사항보고서 (상호변경)", NOTICE, "", f"회사명: {s.name}", f"종목코드: {s.code}",
                 f"접수번호: {doc.rcept_no}", f"제출일: {doc.filed}", "",
                 "1. 변경 내용", f"구 상호 | {s.old_name}", f"신 상호 | {s.name}", f"변경일 | {doc.filed}",
                 "2. 변경 사유: 사업 영역 확대에 따른 기업 이미지 제고",
                 "3. 기타: 종목코드와 법인등록번호는 변경되지 않으며, 변경 전 제출한 공시는 구 상호로 조회됩니다."])
        b.para(self.pick(GOV, 2))
        doc.text = b.text()

    def preliminary_correction(self, doc: Document, original: Document) -> None:
        s, fin = self.s, self.fin
        p0, p1 = fin.preliminary, fin.prelim_corrected
        prev = fin.annual[("연결", 2024)]
        b = Builder(doc)
        b.lines(["[기재정정]연결재무제표기준영업(잠정)실적(공정공시)", NOTICE, "", f"회사명: {s.name}", f"종목코드: {s.code}",
                 f"접수번호: {doc.rcept_no}", f"제출일: {doc.filed}",
                 f"정정대상: {original.report} (제출 {original.filed}, 접수번호 {original.rcept_no})",
                 "정정사유: 결산 조정에 따른 잠정 실적 수정", "※ 동 정보는 잠정치로서 향후 확정치와는 다를 수 있음", "",
                 "정정사항 (단위: 억원) | 정정 전 | 정정 후"])
        for line in ("매출액", "영업이익", "당기순이익"):
            b.line(f"{line} | {fmt(p0[line])} | {fmt(p1[line])}")
        b.lines(["", "1. 연결실적내용 (정정 후)", "(단위: 억원, %)", "구분 | 당기실적 (2025년) | 전기실적 (2024년)"])
        for line in ("매출액", "영업이익", "법인세비용차감전순이익", "당기순이익"):
            b.row(line, [p1[line], int(round(prev[line] / 100))], "억원", [(s.key, "연결", line, "FY2025"), None])
        b.lines(["", "- 상기 실적은 외부감사인의 감사가 완료되지 않은 잠정 수치입니다."])
        doc.text = b.text()


def _fact(doc: Document, key: tuple, offset: int, line_start: int, printed: int, unit: str):
    from .render import Fact
    return Fact(key=key, doc_id=doc.doc_id, offset=offset, line_start=line_start, printed=printed, unit=unit)


def _date(rng: random.Random, y: int, m: int, lo: int, hi: int) -> str:
    return f"{y}.{m:02d}.{rng.randint(lo, hi):02d}"


def build_corpus_v2(seed: int = 21):
    from .questions_v2 import generate_questions_v2
    from .store import Corpus

    rng = random.Random(seed)
    fins: dict[str, CompanyFinancials] = {}
    pending: list[tuple] = []
    rename_date: dict[str, str] = {}
    for spec in company_specs_v2():
        crng = random.Random(rng.randint(0, 2**31))
        fin = generate_financials(spec, crng)
        extend_financials(fin, crng)
        fins[spec.key] = fin
        for year in (2023, 2024, 2025):
            pending.append((_date(rng, year + 1, 3, 10, 20), spec.key, "annual", year))
        pending.append((_date(rng, 2026, 3, 3, 9), spec.key, "audit", 2025))
        pending.append((_date(rng, 2025, 11, 10, 14), spec.key, "q3", 2025))
        if spec.old_name:
            d = _date(rng, 2025, 7, 1, 10)
            rename_date[spec.key] = d
            pending.append((d, spec.key, "rename", 2025))
        if spec.preliminary:
            pending.append((_date(rng, 2026, 1, 20, 30), spec.key, "prelim", 2025))
            if spec.prelim_corrected:
                pending.append((_date(rng, 2026, 2, 10, 20), spec.key, "prelim_correction", 2025))
        if spec.correction:
            pending.append((_date(rng, 2026, 4, 1, 28), spec.key, "annual_correction", 2025))
        pending.append((_date(rng, 2026, 5, 10, 15), spec.key, "q1", 2026))
        pending.append((_date(rng, 2026, 8, 10, 14), spec.key, "half", 2026))
    pending.sort(key=lambda t: (t[0], t[1], t[2]))

    docs: list[Document] = []
    by_kind: dict[tuple, Document] = {}
    reports = {"annual": "사업보고서 ({y}.12)", "annual_correction": "[기재정정]사업보고서 ({y}.12)",
               "audit": "감사보고서 ({y}.12)", "q3": "분기보고서 ({y}.09)", "q1": "분기보고서 ({y}.03)",
               "half": "반기보고서 ({y}.06)", "prelim": "연결재무제표기준영업(잠정)실적(공정공시)",
               "prelim_correction": "[기재정정]연결재무제표기준영업(잠정)실적(공정공시)", "rename": "주요사항보고서(상호변경)"}
    for i, (filed, key, kind, year) in enumerate(pending, start=1):
        spec = fins[key].spec
        name = spec.old_name if spec.old_name and filed < rename_date[key] else spec.name
        doc = Document(doc_id=f"D{i:03d}", company_key=key, company=name, code=spec.code, kind=kind,
                       report=reports[kind].format(y=year), filed=filed, rcept_no=filed.replace(".", "") + f"{700000 + i:06d}")
        docs.append(doc)
        by_kind[(key, kind, year)] = doc

    for doc in docs:
        fin = fins[doc.company_key]
        s = fin.spec
        rend = RendererV2(fin, random.Random(f"v2:{seed}:{doc.doc_id}"))
        if doc.company != s.name:  # filed before the rename: the text carries the old name
            rend.s = dataclasses.replace(s, name=doc.company)
        year = int(doc.report.split("(")[1][:4]) if "(" in doc.report and doc.kind not in ("prelim", "prelim_correction", "rename") else 2025
        if doc.kind in ("annual", "annual_correction", "audit"):
            con = {y: fin.annual[("연결", y)] for y in (year, year - 1, year - 2) if ("연결", y) in fin.annual}
            sep = {y: fin.annual[("별도", y)] for y in con}
            restated = year == 2025 and bool(fin.restated)
            if restated:
                con = dict(con)
                con[2024] = fin.restated[("연결", 2024)]
            unit = s.annual_unit if year == 2025 else "백만원"
            if doc.kind == "audit":
                rend.audit_report(doc, year, {y: v for y, v in con.items() if y >= year - 1},
                                  {y: v for y, v in sep.items() if y >= year - 1}, unit)
                continue
            header = None
            if doc.kind == "annual" and year == 2025 and s.correction:
                con = dict(con)
                con[2025] = fin.annual_original[("연결", 2025)]
                doc.corrected_by = by_kind[(doc.company_key, "annual_correction", 2025)].doc_id
            if doc.kind == "annual_correction":
                orig = by_kind[(doc.company_key, "annual", 2025)]
                doc.corrects = orig.doc_id
                wrong, right = fin.annual_original[("연결", 2025)], fin.annual[("연결", 2025)]
                m = 1000 if unit == "천원" else 1
                header = ["[기재정정]사업보고서", NOTICE, "", "정정신고(보고)", f"정정일자: {doc.filed}",
                          "1. 정정대상 공시서류: 사업보고서 (2025.12)",
                          f"2. 정정대상 공시서류의 최초제출일: {orig.filed} (접수번호 {orig.rcept_no})",
                          "3. 정정사유: 연결포괄손익계산서 및 요약연결재무정보 기재오류 정정",
                          f"4. 정정사항 (단위: {unit})", "항 목 | 정정 전 | 정정 후",
                          f"요약연결재무정보 > 영업이익(손실) | {fmt(wrong['영업이익'] * m)} | {fmt(right['영업이익'] * m)}",
                          f"요약연결재무정보 > 당기순이익(손실) | {fmt(wrong['당기순이익'] * m)} | {fmt(right['당기순이익'] * m)}",
                          "※ 아래는 정정 후 보고서 전문입니다.", "", ""]
            rend.annual_report_v2(doc, year, con, sep, unit, restated_note=restated, correction_header=header)
        elif doc.kind == "prelim":
            rend.preliminary_report(doc)
            if s.prelim_corrected:
                doc.corrected_by = by_kind[(doc.company_key, "prelim_correction", 2025)].doc_id
        elif doc.kind == "prelim_correction":
            orig = by_kind[(doc.company_key, "prelim", 2025)]
            doc.corrects = orig.doc_id
            rend.preliminary_correction(doc, orig)
        elif doc.kind == "rename":
            rend.rename_notice(doc)
        elif doc.kind == "q3":
            rend.quarterly_report_v2(doc, 2025, 3)
        elif doc.kind == "q1":
            rend.quarterly_report_v2(doc, 2026, 1)
        else:
            rend.quarterly_report_v2(doc, 2026, 2)

    facts = [f.to_json() for d in docs for f in d.facts]
    companies = [asdict(f.spec) for f in fins.values()]
    doc_json = [d.to_json() for d in docs]
    digest = hashlib.sha256("".join(d["text"] for d in doc_json).encode("utf-8")).hexdigest()[:16]
    meta = {"version": "v2", "seed": seed, "n_docs": len(doc_json), "n_chars": sum(len(d["text"]) for d in doc_json),
            "sha256_16": digest, "notice": NOTICE}
    corpus = Corpus(doc_json, facts, companies, [], meta)
    corpus.questions = generate_questions_v2(corpus, fins, random.Random(seed + 1))
    corpus.meta["n_questions"] = len(corpus.questions)
    return corpus

"""Build, save and load the synthetic corpus.

Sixteen fictional companies, five filing types, roughly 1.5 million characters in total.
Companies are split by company into a *search* split (used only by the offline Harmony search,
which may look at gold answers) and a *test* split (used for reporting and for the verifier-free
Harness^2 loop). No company appears in both splits, so a harness cannot memorise test facts.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict
from pathlib import Path

from .finance import CompanyFinancials, CompanySpec, generate_financials
from .render import NOTICE, Document, Renderer, fmt

# name, sector, segments, products, ceo, city, founded
COMPANIES = [
    ("hanbit_elec", "한빛전자", "전자부품", ["반도체부품", "디스플레이부품", "기타"], ["정밀 커넥터", "검사 소켓", "FPCB"], "김도현", "경기도 화성시", 1998),
    ("hanbit_power", "한빛전기", "전력기기", ["변압기", "배전반"], ["초고압 변압기", "가스절연개폐장치"], "이재성", "경상남도 창원시", 1987),
    ("sewon_bio", "세원바이오", "바이오의약품", ["원료의약품", "위탁생산"], ["바이오시밀러 원료", "세포배양 배지"], "박서윤", "인천광역시 연수구", 2006),
    ("sewon_biotech", "세원바이오텍", "체외진단", ["진단키트", "진단장비"], ["분자진단 키트", "면역진단 장비"], "최민준", "대전광역시 유성구", 2011),
    ("daeyang_chem", "대양화학", "석유화학", ["기초유분", "합성수지", "특수소재"], ["에틸렌", "폴리프로필렌", "엔지니어링 플라스틱"], "정우진", "울산광역시 남구", 1979),
    ("donghae_heavy", "동해중공업", "조선기자재", ["선박엔진부품", "해양플랜트"], ["크랭크샤프트", "해양 모듈"], "강태호", "부산광역시 강서구", 1990),
    ("mirae_mat", "미래소재", "이차전지 소재", ["양극재", "전구체"], ["하이니켈 양극재", "NCM 전구체"], "윤하늘", "충청북도 청주시", 2009),
    ("cheongsol_food", "청솔식품", "가공식품", ["가공식품", "음료", "수출"], ["즉석밥", "탄산음료", "냉동만두"], "임수아", "전라북도 익산시", 1972),
    ("garam_logis", "가람로지스", "물류", ["육상운송", "해운포워딩", "창고"], ["택배", "국제 포워딩", "콜드체인 창고"], "한지호", "경기도 이천시", 2001),
    ("nuri_games", "누리게임즈", "게임", ["모바일게임", "PC게임", "라이선스"], ["MMORPG", "캐주얼 퍼즐", "IP 라이선스"], "오세린", "경기도 성남시", 2012),
    ("taesung_motors", "태성모터스", "자동차부품", ["구동부품", "전장부품"], ["감속기", "인버터 모듈"], "서민재", "충청남도 아산시", 1985),
    ("ieum_telecom", "이음통신", "통신장비", ["기지국장비", "광전송"], ["5G 무선장비", "광트랜시버"], "신예준", "서울특별시 금천구", 1999),
    ("haram_pharm", "하람제약", "제약", ["전문의약품", "일반의약품"], ["고혈압 복합제", "종합감기약"], "권나연", "경기도 안산시", 1968),
    ("solbit_energy", "솔빛에너지", "신재생에너지", ["태양광모듈", "발전사업"], ["고효율 모듈", "태양광 발전소"], "황준서", "전라남도 나주시", 2008),
    ("geumgang_const", "금강건설", "건설", ["건축", "토목", "플랜트"], ["공동주택", "교량", "정유 플랜트"], "문지후", "서울특별시 송파구", 1976),
    ("daon_retail", "다온유통", "유통", ["오프라인", "온라인"], ["대형마트", "온라인몰"], "배하은", "서울특별시 중구", 1995),
]
SEARCH_SPLIT = {"hanbit_power", "sewon_biotech", "daeyang_chem", "cheongsol_food", "ieum_telecom"}
CORRECTION = {"daeyang_chem", "sewon_biotech", "hanbit_elec", "mirae_mat", "taesung_motors", "haram_pharm"}
PRELIMINARY = {"cheongsol_food", "hanbit_power", "hanbit_elec", "sewon_bio", "garam_logis", "geumgang_const", "haram_pharm"}
THOUSAND_WON = {"ieum_telecom", "hanbit_power", "donghae_heavy", "garam_logis", "solbit_energy", "daon_retail"}


def company_specs() -> list[CompanySpec]:
    specs = []
    for i, (key, name, sector, segs, prods, ceo, city, founded) in enumerate(COMPANIES):
        specs.append(CompanySpec(key=key, name=name, code=f"99{(i + 1) * 10:03d}0"[:6], sector=sector, segments=segs,
                                 products=prods, ceo=ceo, city=city, founded=founded,
                                 correction=key in CORRECTION, preliminary=key in PRELIMINARY,
                                 quarterly_unit="천원" if key in THOUSAND_WON else "백만원",
                                 split="search" if key in SEARCH_SPLIT else "test"))
    return specs


class Corpus:
    def __init__(self, docs: list[dict], facts: list[dict], companies: list[dict], questions: list[dict],
                 meta: dict) -> None:
        self.docs = docs
        self.by_id = {d["doc_id"]: d for d in docs}
        self.facts = facts
        self.companies = companies
        self.company_by_key = {c["key"]: c for c in companies}
        self.questions = questions
        self.meta = meta
        self._facts_by_key: dict[tuple, list[dict]] = {}
        for f in facts:
            self._facts_by_key.setdefault(tuple(f["key"]), []).append(f)

    # -- fact lookup
    def is_valid_source(self, doc: dict) -> bool:
        return doc["kind"] not in ("prelim", "prelim_correction", "rename") and not doc.get("corrected_by")

    def occurrences(self, key: tuple) -> list[dict]:
        return self._facts_by_key.get(tuple(key), [])

    def canonical_fact(self, key: tuple) -> dict:
        """The occurrence in the latest valid filing (corrections win, preliminary figures never count)."""
        occ = [f for f in self.occurrences(key) if self.is_valid_source(self.by_id[f["doc_id"]])]
        if not occ:
            raise KeyError(f"no valid occurrence for {key}")
        return max(occ, key=lambda f: (self.by_id[f["doc_id"]]["filed"], f["doc_id"], -f["offset"]))

    def question(self, qid: str) -> dict:
        for q in self.questions:
            if q["qid"] == qid:
                return q
        raise KeyError(qid)

    def split(self, name: str) -> list[dict]:
        return [q for q in self.questions if q["split"] == name]

    @property
    def n_chars(self) -> int:
        return sum(len(d["text"]) for d in self.docs)

    # -- persistence
    def save(self, out: str | Path) -> Path:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "docs.jsonl", "w", encoding="utf-8") as fh:
            for d in self.docs:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        with open(out / "facts.jsonl", "w", encoding="utf-8") as fh:
            for f in self.facts:
                fh.write(json.dumps(f, ensure_ascii=False) + "\n")
        with open(out / "questions.jsonl", "w", encoding="utf-8") as fh:
            for q in self.questions:
                fh.write(json.dumps(q, ensure_ascii=False) + "\n")
        (out / "companies.json").write_text(json.dumps(self.companies, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "meta.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return out

    @classmethod
    def load(cls, path: str | Path) -> "Corpus":
        path = Path(path)

        def jl(name: str) -> list[dict]:
            with open(path / name, encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]

        return cls(jl("docs.jsonl"), jl("facts.jsonl"),
                   json.loads((path / "companies.json").read_text(encoding="utf-8")), jl("questions.jsonl"),
                   json.loads((path / "meta.json").read_text(encoding="utf-8")))


def _date(rng: random.Random, y: int, m: int, lo: int, hi: int) -> str:
    return f"{y}.{m:02d}.{rng.randint(lo, hi):02d}"


def build_corpus(seed: int = 7) -> Corpus:
    from .questions import generate_questions

    rng = random.Random(seed)
    fins: list[CompanyFinancials] = []
    pending: list[tuple] = []  # (filed, company_key, kind, extra)
    for spec in company_specs():
        fin = generate_financials(spec, random.Random(rng.randint(0, 2**31)))
        fins.append(fin)
        for year in (2023, 2024, 2025):
            pending.append((_date(rng, year + 1, 3, 10, 20), spec.key, "annual", year))
        if spec.preliminary:
            m = rng.choice([1, 2])
            pending.append((_date(rng, 2026, m, 20 if m == 1 else 2, 30 if m == 1 else 14), spec.key, "prelim", 2025))
        if spec.correction:
            pending.append((_date(rng, 2026, 4, 1, 28), spec.key, "annual_correction", 2025))
        pending.append((_date(rng, 2026, 5, 10, 15), spec.key, "q1", 2026))
        pending.append((_date(rng, 2026, 8, 10, 14), spec.key, "half", 2026))
    pending.sort(key=lambda t: (t[0], t[1], t[2]))
    fin_by_key = {f.spec.key: f for f in fins}

    docs: list[Document] = []
    by_company_kind: dict[tuple, Document] = {}
    for i, (filed, key, kind, year) in enumerate(pending, start=1):
        spec = fin_by_key[key].spec
        report = {"annual": f"사업보고서 ({year}.12)", "annual_correction": f"[기재정정]사업보고서 ({year}.12)",
                  "prelim": "연결재무제표기준영업(잠정)실적(공정공시)", "q1": "분기보고서 (2026.03)",
                  "half": "반기보고서 (2026.06)"}[kind]
        doc = Document(doc_id=f"D{i:03d}", company_key=key, company=spec.name, code=spec.code, kind=kind,
                       report=report, filed=filed, rcept_no=filed.replace(".", "") + f"{800000 + i:06d}")
        docs.append(doc)
        by_company_kind[(key, kind, year)] = doc

    for doc in docs:
        fin = fin_by_key[doc.company_key]
        rend = Renderer(fin, random.Random(f"{seed}:{doc.doc_id}"))
        if doc.kind in ("annual", "annual_correction"):
            year = int(doc.report.split("(")[1][:4])
            con = {y: fin.annual[("연결", y)] for y in (year, year - 1, year - 2) if ("연결", y) in fin.annual}
            sep = {y: fin.annual[("별도", y)] for y in con}
            header = None
            if doc.kind == "annual" and year == 2025 and fin.spec.correction:
                con = dict(con)
                con[2025] = fin.annual_original[("연결", 2025)]
                corr = by_company_kind[(doc.company_key, "annual_correction", 2025)]
                doc.corrected_by = corr.doc_id
            if doc.kind == "annual_correction":
                orig = by_company_kind[(doc.company_key, "annual", 2025)]
                doc.corrects = orig.doc_id
                wrong, right = fin.annual_original[("연결", 2025)], fin.annual[("연결", 2025)]
                header = ["[기재정정]사업보고서", NOTICE, "", "정정신고(보고)", f"정정일자: {doc.filed}",
                          "1. 정정대상 공시서류: 사업보고서 (2025.12)",
                          f"2. 정정대상 공시서류의 최초제출일: {orig.filed} (접수번호 {orig.rcept_no})",
                          "3. 정정사유: 연결포괄손익계산서 및 요약연결재무정보 기재오류 정정",
                          "4. 정정사항 (단위: 백만원)", "항 목 | 정정 전 | 정정 후",
                          f"요약연결재무정보 > 영업이익(손실) | {fmt(wrong['영업이익'])} | {fmt(right['영업이익'])}",
                          f"요약연결재무정보 > 당기순이익(손실) | {fmt(wrong['당기순이익'])} | {fmt(right['당기순이익'])}",
                          "※ 아래는 정정 후 보고서 전문입니다.", "", ""]
            rend.annual_report(doc, year, con, sep, correction_header=header)
        elif doc.kind == "prelim":
            rend.preliminary_report(doc)
        elif doc.kind == "q1":
            rend.quarterly_report(doc, 1)
        else:
            rend.quarterly_report(doc, 2)

    facts = [f.to_json() for d in docs for f in d.facts]
    companies = []
    for f in fins:
        c = asdict(f.spec)
        companies.append(c)
    doc_json = [d.to_json() for d in docs]
    digest = hashlib.sha256("".join(d["text"] for d in doc_json).encode("utf-8")).hexdigest()[:16]
    meta = {"seed": seed, "n_docs": len(doc_json), "n_chars": sum(len(d["text"]) for d in doc_json),
            "sha256_16": digest, "notice": NOTICE}
    corpus = Corpus(doc_json, facts, companies, [], meta)
    corpus.questions = generate_questions(corpus, fin_by_key, random.Random(seed + 1))
    corpus.meta["n_questions"] = len(corpus.questions)
    return corpus

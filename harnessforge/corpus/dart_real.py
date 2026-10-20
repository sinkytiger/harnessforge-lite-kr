"""A small real-filing set: FY2025 annual reports of a few listed companies, from DART OpenAPI.

    python -m harnessforge build-real --out data/dart_real

Needs your own DART key in the DART_API_KEY environment variable (free at https://opendart.fss.or.kr).
The key is read from the environment only; it is never printed or written to disk.

* Documents: the latest FY2025 사업보고서 of each company (original or [기재정정]), converted from DART
  XML to plain text with table rows joined by " | ". Raw filings are cached under the output folder
  and are not part of the repository.
* Gold answers: the consolidated full financial statements API (fnlttSinglAcntAll, CFS). A question
  is kept only when its figure can be found printed in the filing text (in 원, 천원 or 백만원), so
  every question is answerable from the documents; the oracle replays it through the tools.
* Two unanswerable questions are added, as in v2.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .questions import BASIS, EOK_SPEC, PCT_SPEC
from .questions_v2 import ABSTAIN_CLAUSE, ABSTAIN_GOLD
from .store import Corpus

BASE = "https://opendart.fss.or.kr/api/"
KEY_ENV = "DART_API_KEY"
COMPANIES = [  # corp codes verified against company.json in finground-lite-kr
    ("00126380", "삼성전자"), ("00164742", "현대자동차"), ("00266961", "NAVER"),
    ("00258801", "카카오"), ("00401731", "LG전자"), ("00155319", "POSCO홀딩스"),
]
ACCOUNTS = {
    "매출액": ("ifrs-full_Revenue",),
    "영업이익": ("dart_OperatingIncomeLoss",),
    "당기순이익": ("ifrs-full_ProfitLoss",),
    "자산총계": ("ifrs-full_Assets",),
    "부채총계": ("ifrs-full_Liabilities",),
    "자본총계": ("ifrs-full_Equity",),
}
NOTICE_REAL = "※ 실제 DART 공시 원문을 연구용 텍스트로 변환한 문서입니다. 수치는 원문과 DART 재무 API를 따릅니다."


class DartError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get(KEY_ENV, "").strip()
    if not k:
        raise DartError(f"{KEY_ENV} is not set; get a free key at https://opendart.fss.or.kr and export it yourself")
    return k


def _get(endpoint: str, cache: Path, name: str, **params) -> bytes:
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / name
    if f.exists():
        return f.read_bytes()
    params["crtfc_key"] = _key()
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            break
        except OSError:
            if attempt == 2:
                raise DartError(f"cannot reach DART for {endpoint}")
            time.sleep(5)
    if endpoint.endswith(".json"):
        status = json.loads(data.decode("utf-8")).get("status")
        if status not in ("000", "013"):
            raise DartError(f"DART {endpoint} returned status {status}")
    f.write_bytes(data)
    return data


_ROW = re.compile(r"(?is)<TR\b[^>]*>(.*?)</TR>")
_CELL = re.compile(r"(?is)<(TD|TH|TE|TU)\b[^>]*>(.*?)</\1>")


def _inline(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _row(m: re.Match) -> str:
    cells = [_inline(c.group(2)) for c in _CELL.finditer(m.group(1))]
    while cells and not cells[-1]:
        cells.pop()
    return "\n" + " | ".join(cells) + "\n"  # empty cells are kept so columns stay aligned


def xml_to_text(raw: str) -> str:
    """DART XML (dart4) to plain text: one line per paragraph or title, one ' | ' line per table row."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    s = _ROW.sub(_row, s)
    s = re.sub(r"(?i)</(P|TITLE|SPAN-TITLE|TABLE-GROUP|TABLE)>|<BR\s*/?>", "\n", s)
    s = re.sub(r"(?i)<(TITLE|P)\b[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = []
    for line in s.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r"^\|\s*", "", line)
        if line and line != "|":
            lines.append(line)
    return "\n".join(lines)


def _latest_annual(corp: str, cache: Path) -> dict:
    lst = json.loads(_get("list.json", cache, f"list_{corp}.json", corp_code=corp, bgn_de="20260101",
                          end_de="20261231", pblntf_ty="A", page_count=100).decode("utf-8"))
    annual = [it for it in lst.get("list", []) if "사업보고서 (2025.12)" in it["report_nm"]]
    if not annual:
        raise DartError(f"no FY2025 annual report for {corp}")
    return max(annual, key=lambda it: it["rcept_no"])


def _norm(name: str) -> str:
    return re.sub(r"[\s()（）]|\d+\.|[ⅠⅡⅢⅣⅤIVX]+\.", "", name or "")


NAMES = {"매출액": {"매출액", "수익(매출액)", "영업수익", "매출", "매출액(영업수익)"}, "영업이익": {"영업이익", "영업이익(손실)"},
         "당기순이익": {"당기순이익", "당기순이익(손실)"}, "자산총계": {"자산총계"}, "부채총계": {"부채총계"},
         "자본총계": {"자본총계"}}


def _statements(corp: str, cache: Path) -> dict:
    data = json.loads(_get("fnlttSinglAcntAll.json", cache, f"fs_{corp}_2025_CFS.json", corp_code=corp,
                           bsns_year="2025", reprt_code="11011", fs_div="CFS").decode("utf-8"))
    rows = [r for r in data.get("list", []) if r.get("sj_div") in ("BS", "IS", "CIS")]

    def num(v):
        v = (v or "").replace(",", "").strip()
        return int(v) if re.fullmatch(r"-?\d+", v) else None

    out = {}
    for metric, ids in ACCOUNTS.items():
        names = {_norm(n) for n in NAMES[metric]}
        row = (next((r for r in rows if r.get("account_id") in ids), None)
               or next((r for r in rows if _norm(r.get("account_nm")) in names), None))
        if row:
            out[metric] = {"cur": num(row.get("thstrm_amount")), "prev": num(row.get("frmtrm_amount")),
                           "label": row.get("account_nm", metric)}
    return out


DIV = {"백만원": 1_000_000, "천원": 1_000, "원": 1}
_UNIT_HDR = re.compile(r"단위\s*[:：]?\s*(백만원|천원|원)")


def _unit_before(text: str, pos: int, window: int = 20_000) -> str | None:
    last = None
    for m in _UNIT_HDR.finditer(text, max(0, pos - window), pos):
        last = m.group(1)
    return last


def _locate(text: str, won: int) -> tuple[int, int, str, int] | None:
    """Find the figure as printed in the filing (백만원, 천원 or 원), under a table header of that unit."""
    for unit, div in DIV.items():
        for v in dict.fromkeys((round(won / div), int(won / div))):
            if abs(v) < 10_000:  # short numbers are ambiguous
                continue
            pat = r"(?<![\d,.])" + re.escape(f"{abs(v):,}") + r"(?![\d]|[,.]\d)"
            for m in re.finditer(pat, text):
                if _unit_before(text, m.start()) == unit:
                    return m.start(), text.rfind("\n", 0, m.start()) + 1, unit, v
    return None


def build_real(out: str | Path = "data/dart_real", companies=COMPANIES) -> Corpus:
    out = Path(out)
    cache = out / "cache"
    docs, facts, comps, questions = [], [], [], []
    for i, (corp, name) in enumerate(companies, start=1):
        it = _latest_annual(corp, cache)
        raw = _get("document.xml", cache, f"doc_{it['rcept_no']}.zip", rcept_no=it["rcept_no"])
        z = zipfile.ZipFile(io.BytesIO(raw))
        main = min(z.namelist(), key=len)  # the main report; the others are attached audit reports
        text = NOTICE_REAL + "\n" + xml_to_text(z.read(main).decode("utf-8", "replace"))
        doc_id = f"R{i:03d}"
        filed = f"{it['rcept_dt'][:4]}.{it['rcept_dt'][4:6]}.{it['rcept_dt'][6:]}"
        docs.append({"doc_id": doc_id, "company_key": corp, "company": name, "code": it.get("stock_code", ""),
                     "kind": "annual_correction" if "정정" in it["report_nm"] else "annual",
                     "report": it["report_nm"].strip(), "filed": filed, "rcept_no": it["rcept_no"],
                     "corrects": None, "corrected_by": None, "text": text})
        comps.append({"key": corp, "name": name, "split": "real"})
        st = _statements(corp, cache)
        located = {}
        for metric, v in st.items():
            for col, year in (("cur", "FY2025"), ("prev", "FY2024")):
                won = v.get(col)
                if won is None:
                    continue
                hit = _locate(text, won)
                if hit:
                    off, ls, unit, printed = hit
                    fact = {"key": [corp, "연결", metric, year], "doc_id": doc_id, "offset": off, "line_start": ls,
                            "printed": printed, "unit": unit}
                    facts.append(fact)
                    located[(metric, year)] = fact
        questions += _real_questions(name, corp, located, i - 1)
    questions += [
        {"qtype": "abstain_future_period", "company_key": COMPANIES[0][0], "companies": [COMPANIES[0][1]],
         "text": f"{COMPANIES[0][1]}의 2026년 4분기(10~12월, 3개월) 연결 기준 매출액은 몇 억원인가? {BASIS} {EOK_SPEC} {ABSTAIN_CLAUSE}",
         "unit": "", "gold": ABSTAIN_GOLD, "answer_type": "abstain", "tol_abs": 0.0, "tol_rel": 0.0,
         "calc": {"abstain": True}, "traps": {}, "split": "real"},
        {"qtype": "abstain_unknown_company", "company_key": "none", "companies": ["한결나노소재"],
         "text": f"한결나노소재의 2025 사업연도 연결 기준 매출액은 몇 억원인가? {BASIS} {EOK_SPEC} {ABSTAIN_CLAUSE}",
         "unit": "", "gold": ABSTAIN_GOLD, "answer_type": "abstain", "tol_abs": 0.0, "tol_rel": 0.0,
         "calc": {"abstain": True}, "traps": {}, "split": "real"},
    ]
    for n, q in enumerate(questions, start=1):
        q["qid"] = f"R{n:02d}_{q['qtype']}"
    digest = hashlib.sha256("".join(d["text"] for d in docs).encode("utf-8")).hexdigest()[:16]
    meta = {"version": "real", "n_docs": len(docs), "n_chars": sum(len(d["text"]) for d in docs), "sha256_16": digest,
            "rcept_no": [d["rcept_no"] for d in docs], "notice": NOTICE_REAL, "n_questions": len(questions)}
    corpus = Corpus(docs, facts, comps, questions, meta)
    corpus.save(out)
    return corpus


def _real_questions(name: str, corp: str, f: dict, rot: int = 0) -> list[dict]:
    from ..calc import evaluate
    TO = {"백만원": 100, "천원": 100_000, "원": 100_000_000}

    def q(qtype, text, unit, facts, expr):
        gold = evaluate(expr, {f"F{i}": x["printed"] for i, x in enumerate(facts)})
        return {"qtype": qtype, "company_key": corp, "companies": [name], "text": f"{text} {ABSTAIN_CLAUSE}", "unit": unit,
                "gold": gold, "answer_type": "number", "tol_abs": 0.15 if unit == "억원" else 0.05,
                "tol_rel": 0.002 if unit == "억원" else 0.0, "calc": {"expr": expr, "facts": facts}, "traps": {}, "split": "real"}

    out = {}
    rev = "매출액(영업수익)"
    if ("매출액", "FY2025") in f:
        x = f[("매출액", "FY2025")]
        out["rev_eok"] = (q("rev_eok", f"{name}의 2025 사업연도 연결 기준 {rev}은 몇 억원인가? {BASIS} {EOK_SPEC}", "억원", [x], f"F0 / {TO[x['unit']]}"))
    if ("영업이익", "FY2025") in f and ("매출액", "FY2025") in f:
        a, b = f[("영업이익", "FY2025")], f[("매출액", "FY2025")]
        if a["unit"] == b["unit"]:
            out["op_margin"] = (q("op_margin", f"{name}의 2025 사업연도 연결 기준 영업이익률(영업이익 ÷ {rev})은 몇 %인가? {BASIS} {PCT_SPEC}",
                         "%", [a, b], "F0 / F1 * 100"))
    if ("부채총계", "FY2025") in f and ("자본총계", "FY2025") in f:
        a, b = f[("부채총계", "FY2025")], f[("자본총계", "FY2025")]
        if a["unit"] == b["unit"]:
            out["debt_ratio"] = (q("debt_ratio", f"{name}의 2025 사업연도 말 연결 기준 부채비율(부채총계 ÷ 자본총계)은 몇 %인가? {BASIS} {PCT_SPEC}",
                         "%", [a, b], "F0 / F1 * 100"))
    if ("매출액", "FY2025") in f and ("매출액", "FY2024") in f:
        a, b = f[("매출액", "FY2025")], f[("매출액", "FY2024")]
        if a["unit"] == b["unit"]:
            out["rev_growth"] = (q("rev_growth", f"{name}의 2025 사업연도 연결 {rev}은 전년 대비 몇 % 증가했는가? {BASIS} {PCT_SPEC}",
                         "%", [a, b], "(F0 / F1 - 1) * 100"))
    order = ["rev_eok", "op_margin", "debt_ratio", "rev_growth"]
    order = order[rot % 4:] + order[:rot % 4]  # vary which three types each company gets
    return [out[t] for t in order if t in out][:3]


def load_real(path: str | Path = "data/dart_real") -> Corpus:
    p = Path(path)
    if not (p / "docs.jsonl").exists():
        raise FileNotFoundError(f"{p} has no real-filing set; build it with: python -m harnessforge build-real --out {p}")
    return Corpus.load(p)

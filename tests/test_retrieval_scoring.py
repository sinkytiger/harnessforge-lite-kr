import pytest

from harnessforge.calc import CalcError, evaluate
from harnessforge.retrieval import tokenize
from harnessforge.scoring import parse_number, score


def test_tokenize_uses_hangul_bigrams_and_strips_separators():
    toks = tokenize("영업이익은 12,345 백만원")
    assert "영업" in toks and "이익" in toks and "12345" in toks


def test_search_with_company_filter_finds_the_summary_table(corpus, index):
    company = corpus.companies[0]["name"]
    hits = index.search(f"{company} 요약연결재무정보 매출액", k=5, company=company)
    assert hits and all(company in h["title"] for h in hits)
    assert any("요약연결재무정보" in h["section"] for h in hits)


def test_regex_search(index):
    hits = index.regex(r"^\[기재정정\]", k=3)
    assert hits and all("[기재정정]" in h["snippet"] for h in hits)


@pytest.mark.parametrize("text,value", [("1,234.5", 1234.5), ("△12.3", -12.3), ("-7", -7.0), ("약 28,420.7억원", 28420.7),
                                        ("12.34%", 12.34), ("(1,000)", -1000.0), ("2.5조원", 25000.0)])
def test_parse_number(text, value):
    assert parse_number(text) == pytest.approx(value)


def test_score_numeric_and_traps(corpus):
    q = next(q for q in corpus.questions if q["answer_type"] == "number" and "before_correction" in q["traps"])
    assert score(q, f"{q['gold']:.2f}")["correct"]
    res = score(q, f"{q['traps']['before_correction']:.2f}")
    assert not res["correct"] and res["trap"] == "before_correction"
    assert score(q, None)["status"] == "no_answer"


def test_score_entity(corpus):
    q = next(q for q in corpus.questions if q["answer_type"] == "entity")
    assert score(q, q["gold"])["correct"]
    other = [n for n in q["companies"] if n != q["gold"]][0]
    assert not score(q, other)["correct"]
    assert not score(q, f"{q['gold']}와 {other}")["correct"]


def test_calc_is_safe():
    assert evaluate("(E1 - E2) / E2 * 100", {"E1": 110, "E2": 100}) == pytest.approx(10)
    assert evaluate("1,234 / 2") == pytest.approx(617)
    assert evaluate("(E1 / E2) ** 0.5", {"E1": 121, "E2": 100}) == pytest.approx(1.1)
    for bad in ("__import__('os')", "E1 ** E1", "2 ** 10", "(-8) ** 0.5", "abs(-1)", "E9 + 1"):
        with pytest.raises(CalcError):
            evaluate(bad, {"E1": 1})


def test_unit_slip_detected_for_any_power_of_ten(corpus):
    q = next(q for q in corpus.questions if q["unit"] == "억원")
    assert score(q, f"{q['gold'] * 100:.1f}")["trap"] in ("unit_slip",) or "unit_slip" in q["traps"]
    assert score(q, f"{q['gold'] * 10:.2f}")["trap"] == "unit_slip"


@pytest.mark.parametrize("text,value", [("1조 2,345.6억원", 12345.6), ("2025년 12.34", 12.34), ("제 31 기 697.7", 697.7),
                                        ("2분기 616.2억원", 616.2), ("△1조", -10000.0)])
def test_parse_number_skips_periods_and_reads_jo(text, value):
    assert parse_number(text) == pytest.approx(value)

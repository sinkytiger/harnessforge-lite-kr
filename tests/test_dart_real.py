"""The real-filing set is fetched by each user with their own DART key; these tests stay offline."""

import pytest

from harnessforge.corpus import dart_real
from harnessforge.corpus.dart_real import DartError, _locate, _real_questions, xml_to_text

XML = """<DOCUMENT><BODY><TITLE ATOC="Y">III. 재무에 관한 사항</TITLE>
<P>가. 요약연결재무정보</P><P>(단위 : 백만원)</P>
<TABLE><TBODY>
<TR><TH>구 분</TH><TH>제57기</TH><TH>제56기</TH></TR>
<TR><TD><P>매출액</P></TD><TE>333,605,938</TE><TE>300,870,903</TE></TR>
<TR><TD>영업이익</TD><TE>43,601,051</TE><TE>32,725,961</TE><TD></TD></TR>
</TBODY></TABLE>
<P>본문 문단&amp;설명</P></BODY></DOCUMENT>"""


def test_xml_rows_become_single_lines():
    text = xml_to_text(XML)
    lines = text.split("\n")
    assert "구 분 | 제57기 | 제56기" in lines
    assert "매출액 | 333,605,938 | 300,870,903" in lines   # a <P> inside a cell does not split the row
    assert "영업이익 | 43,601,051 | 32,725,961" in lines  # trailing empty cells are dropped
    assert "본문 문단&설명" in lines


def test_locate_needs_the_unit_header():
    text = xml_to_text(XML)
    off, line_start, unit, printed = _locate(text, 333_605_938_123_456)
    assert unit == "백만원" and printed == 333_605_938
    assert text[off:off + 11] == "333,605,938" and text[line_start:].startswith("매출액")
    # the same digits without a 백만원 table header are not accepted as a 백만원 figure
    assert _locate("매출액 | 333,605,938", 333_605_938_000_000) is None


def test_questions_use_the_printed_figures():
    f = {("매출액", "FY2025"): {"key": ["c", "연결", "매출액", "FY2025"], "doc_id": "R001", "offset": 0, "line_start": 0,
                               "printed": 333_605_938, "unit": "백만원"},
         ("매출액", "FY2024"): {"key": ["c", "연결", "매출액", "FY2024"], "doc_id": "R001", "offset": 0, "line_start": 0,
                               "printed": 300_870_903, "unit": "백만원"}}
    qs = _real_questions("삼성전자", "00126380", f)
    by = {q["qtype"]: q for q in qs}
    assert by["rev_eok"]["gold"] == pytest.approx(3_336_059.38)
    assert by["rev_growth"]["gold"] == pytest.approx((333_605_938 / 300_870_903 - 1) * 100)
    assert all(q["split"] == "real" and q["text"].endswith(dart_real.ABSTAIN_CLAUSE) for q in qs)


def test_missing_key_is_reported_without_a_request(monkeypatch, tmp_path):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    with pytest.raises(DartError, match="DART_API_KEY"):
        dart_real._get("list.json", tmp_path, "x.json", corp_code="00126380")
    assert not list(tmp_path.iterdir())

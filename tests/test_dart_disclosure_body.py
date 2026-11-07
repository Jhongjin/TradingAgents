"""get_disclosure_body / get_disclosures_with_bodies — stdlib-only DART body parser.

No network: every test builds its own zip bytes in memory, patterned on the
real filings captured for the PoC
(jobs/2026-11-06-trading-repo-review/poc-dart/raw in the production-hub repo —
dart4 TD/TE/TU schema for 전환사채 and plain <table> HTML for 공정공시 실적).
"""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from tradingagents.dataflows import dart


def _zip_bytes(filename: str, content: str) -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w") as archive:
        archive.writestr(filename, content.encode("utf-8"))
    return buf.getvalue()


# A trimmed dart4 schema body: TD carries the label, TE/TU carry the value,
# same shape as the real 전환사채권발행결정 filing (poc-dart RESULT.md).
_DART_SCHEMA_XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="dart4.xsd">
<BODY>
<TABLE>
<TBODY>
<TR><TD>권면총액(원)</TD><TE ACODE="DNM_SUM">30,000,000,000</TE></TR>
<TR><TD>전환가액(원/주)</TD><TU AUNIT="CVP_PPS">4,290</TU></TR>
<TR><TD COLSPAN="2"></TD></TR>
</TBODY>
</TABLE>
<P>{prose}</P>
</BODY>
</DOCUMENT>"""

# Plain HTML <table>, same shape as the 공정공시 영업(잠정)실적 filing.
_HTML_TABLE = """<html><body><table>
<tr><td>매출액</td><td>129,250</td></tr>
<tr><td>영업이익</td><td>4,039</td></tr>
<tr><td>당기순이익</td><td>-9,091</td></tr>
</table></body></html>"""


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    # Every test gets its own cache dir so body-cache writes never touch (or
    # read stale data from) a real user's ~/.tradingagents/cache.
    monkeypatch.setenv("TRADINGAGENTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("DART_API_KEY", "test-key")


def test_dart_schema_flattens_td_te_tu_rows_as_label_value(monkeypatch):
    xml_text = _DART_SCHEMA_XML.format(prose="단기 사항 없음.")
    monkeypatch.setattr(dart, "_request_binary", lambda endpoint, params: _zip_bytes("body.xml", xml_text))

    result = dart.get_disclosure_body("20261106000165")

    assert "권면총액(원) | 30,000,000,000" in result
    assert "전환가액(원/주) | 4,290" in result
    # The empty TD-only row (a layout spacer in the real filings) must not
    # produce a stray "|" line.
    assert "\n | \n" not in result


def test_html_table_filing_is_parsed_without_dart_schema_tags(monkeypatch):
    monkeypatch.setattr(dart, "_request_binary", lambda endpoint, params: _zip_bytes("body.xml", _HTML_TABLE))

    result = dart.get_disclosure_body("20261106900830")

    assert "매출액 | 129,250" in result
    assert "영업이익 | 4,039" in result
    assert "당기순이익 | -9,091" in result


def test_long_cell_is_truncated_with_ellipsis(monkeypatch):
    long_clause = "가" * 500  # articles-of-incorporation-style long quote
    xml_text = _DART_SCHEMA_XML.format(prose=long_clause)
    monkeypatch.setattr(dart, "_request_binary", lambda endpoint, params: _zip_bytes("body.xml", xml_text))

    result = dart.get_disclosure_body("20261106000165", max_cell_chars=50)

    prose_line = [line for line in result.splitlines() if line.startswith("가")][0]
    assert len(prose_line) == 50
    assert prose_line.endswith("…")


def test_max_rows_caps_output_row_count(monkeypatch):
    rows = "".join(f"<TR><TD>항목{i}</TD><TE>{i}</TE></TR>" for i in range(10))
    xml_text = f"""<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT xsi:noNamespaceSchemaLocation="dart4.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<BODY><TABLE><TBODY>{rows}</TBODY></TABLE></BODY></DOCUMENT>"""
    monkeypatch.setattr(dart, "_request_binary", lambda endpoint, params: _zip_bytes("body.xml", xml_text))

    result = dart.get_disclosure_body("20261106000999", max_rows=3)

    assert len(result.splitlines()) == 3
    assert "항목0 | 0" in result
    assert "항목9 | 9" not in result


def test_malformed_zip_fails_closed_without_raising(monkeypatch):
    monkeypatch.setattr(dart, "_request_binary", lambda endpoint, params: b"this is not a zip file")

    result = dart.get_disclosure_body("20261106000165")

    assert "disclosure body parse failed" in result
    # The failure message must never echo the raw garbage bytes or any key.
    assert "test-key" not in result


def test_request_binary_failure_never_leaks_api_key(monkeypatch):
    import requests

    class _FakeResponse:
        def raise_for_status(self):
            raise requests.HTTPError(
                "404 Client Error: Not Found for url: "
                "https://opendart.fss.or.kr/api/document.xml?crtfc_key=test-key&rcept_no=x"
            )

    monkeypatch.setattr(dart.requests, "get", lambda *a, **k: _FakeResponse())

    with pytest.raises(dart.VendorUnavailableError) as excinfo:
        dart._request_binary("document.xml", {"rcept_no": "x"})

    assert "test-key" not in str(excinfo.value)


def test_cache_hit_avoids_second_network_call(monkeypatch):
    xml_text = _DART_SCHEMA_XML.format(prose="단기 사항 없음.")
    calls = {"count": 0}

    def fake_request_binary(endpoint, params):
        calls["count"] += 1
        return _zip_bytes("body.xml", xml_text)

    monkeypatch.setattr(dart, "_request_binary", fake_request_binary)

    first = dart.get_disclosure_body("20261106000165")
    second = dart.get_disclosure_body("20261106000165")

    assert first == second
    assert calls["count"] == 1  # second call served from the on-disk cache


def test_report_type_filter_only_fetches_bodies_for_decision_relevant_filings(monkeypatch):
    rows = [
        {"receipt_no": "1", "report_name": "전환사채권발행결정", "filed_at": "20261106", "filer": "", "ticker_code": "005930", "ticker_name": "삼성전자", "url": ""},
        {"receipt_no": "2", "report_name": "기타공시", "filed_at": "20261105", "filer": "", "ticker_code": "005930", "ticker_name": "삼성전자", "url": ""},
        {"receipt_no": "3", "report_name": "유상증자결정", "filed_at": "20261104", "filer": "", "ticker_code": "005930", "ticker_name": "삼성전자", "url": ""},
        {"receipt_no": "4", "report_name": "최대주주변경", "filed_at": "20261103", "filer": "", "ticker_code": "005930", "ticker_name": "삼성전자", "url": ""},
        {"receipt_no": "5", "report_name": "자기주식취득결정", "filed_at": "20261102", "filer": "", "ticker_code": "005930", "ticker_name": "삼성전자", "url": ""},
    ]
    monkeypatch.setattr(dart, "list_recent_disclosures", lambda *a, **k: rows)
    fetched_ids = []

    def fake_get_disclosure_body(rcept_no, **kwargs):
        fetched_ids.append(rcept_no)
        return f"BODY-{rcept_no}"

    monkeypatch.setattr(dart, "get_disclosure_body", fake_get_disclosure_body)

    result = dart.get_disclosures_with_bodies("005930", max_bodies=3)

    # 5 filings qualify by keyword but the cap is 3, and "기타공시" never qualifies.
    assert fetched_ids == ["1", "3", "4"]
    assert "기타공시" in result  # title stays even though no body was fetched
    assert "BODY-5" not in result
    assert "BODY-1" in result and "BODY-3" in result and "BODY-4" in result


def test_report_type_filter_matches_amendment_suffix():
    assert dart._is_body_worthy("전환사채권발행결정(정정)")
    assert dart._is_body_worthy("의무보유 확약 현황")
    assert not dart._is_body_worthy("단순 안내공시")


def test_disclosures_with_bodies_keeps_title_list_when_one_body_fetch_fails(monkeypatch):
    rows = [
        {"receipt_no": "1", "report_name": "전환사채권발행결정", "filed_at": "20261106", "filer": "", "ticker_code": "005930", "ticker_name": "삼성전자", "url": ""},
    ]
    monkeypatch.setattr(dart, "list_recent_disclosures", lambda *a, **k: rows)

    def failing_get_disclosure_body(rcept_no, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(dart, "get_disclosure_body", failing_get_disclosure_body)

    result = dart.get_disclosures_with_bodies("005930")

    assert "20261106 | 전환사채권발행결정 | 1" in result
    assert "body unavailable for 1" in result

"""OpenDART disclosure and financial-statement vendor."""

from __future__ import annotations

from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from io import BytesIO
from typing import Annotated, Any

import requests

from .errors import VendorUnavailableError
from .kr_tickers import is_kr_ticker, resolve_kr_ticker

_BASE_URL = "https://opendart.fss.or.kr/api"
_COMMON_CORP_CODES = {
    "005930": "00126380",
    "000660": "00164779",
    "035420": "00266961",
}
_REPORT_CODE_LABELS = {
    "11011": "Annual report",
    "11013": "Q1 report",
    "11012": "Half-year report",
    "11014": "Q3 report",
}


def get_fundamentals(
    ticker: Annotated[str, "Korean 6-digit ticker symbol"],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"] = None,
) -> str:
    resolved = _require_supported(ticker)
    corp_code = get_corp_code(resolved.code)
    profile = _request_json("company.json", {"corp_code": corp_code})
    disclosures = _recent_disclosures(corp_code, curr_date, days=45, limit=10)

    lines = [
        f"# DART fundamentals for {resolved.name} ({resolved.code}, {resolved.market})",
        f"- Corporate registration code: {profile.get('corp_code', corp_code)}",
        f"- Corporation name: {profile.get('corp_name', resolved.name)}",
        f"- CEO: {profile.get('ceo_nm', 'n/a')}",
        f"- Industry: {profile.get('induty_code', 'n/a')}",
        f"- Establishment date: {profile.get('est_dt', 'n/a')}",
        f"- Fiscal month: {profile.get('acc_mt', 'n/a')}",
        "",
        "## Recent DART disclosures",
    ]
    lines.extend(disclosures)
    return "\n".join(lines)


def get_balance_sheet(
    ticker: Annotated[str, "Korean 6-digit ticker symbol"],
    freq: Annotated[str, "reporting frequency"] = "annual",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    return _financial_statement(ticker, curr_date, freq, "BS", "Balance Sheet")


def get_cashflow(
    ticker: Annotated[str, "Korean 6-digit ticker symbol"],
    freq: Annotated[str, "reporting frequency"] = "annual",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    return _financial_statement(ticker, curr_date, freq, "CF", "Cash Flow")


def get_income_statement(
    ticker: Annotated[str, "Korean 6-digit ticker symbol"],
    freq: Annotated[str, "reporting frequency"] = "annual",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    return _financial_statement(ticker, curr_date, freq, "IS", "Income Statement")


def get_insider_transactions(ticker: Annotated[str, "Korean 6-digit ticker symbol"]) -> str:
    resolved = _require_supported(ticker)
    corp_code = get_corp_code(resolved.code)
    disclosures = _recent_disclosures(corp_code, None, days=365, limit=30)
    keywords = ("임원", "주요주주", "대량보유", "소유상황", "지분")
    selected = [line for line in disclosures if any(keyword in line for keyword in keywords)]
    if not selected:
        return f"No recent DART ownership-related disclosures found for {resolved.name} ({resolved.code})"
    return "\n".join([f"# DART ownership disclosures for {resolved.name} ({resolved.code})", *selected[:10]])


def list_recent_disclosures(
    ticker: Annotated[str, "Korean 6-digit ticker symbol"],
    *,
    days: int = 2,
    limit: int = 30,
    curr_date: str | None = None,
) -> list[dict[str, Any]]:
    """Recent filings as rows, for alerting rather than prompting.

    The prompt-facing helpers format disclosures into text; a notifier needs
    the receipt number to tell a new filing from one already sent.
    """

    resolved = _require_supported(ticker)
    corp_code = get_corp_code(resolved.code)
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d") if curr_date else datetime.now()
    start_dt = end_dt - timedelta(days=max(days, 1))
    payload = _request_json(
        "list.json",
        {
            "corp_code": corp_code,
            "bgn_de": start_dt.strftime("%Y%m%d"),
            "end_de": end_dt.strftime("%Y%m%d"),
            "page_count": str(limit),
        },
    )
    rows = []
    for row in payload.get("list", []) or []:
        receipt = str(row.get("rcept_no") or "").strip()
        if not receipt:
            continue
        rows.append(
            {
                "receipt_no": receipt,
                "report_name": str(row.get("report_nm") or "").strip(),
                "filed_at": str(row.get("rcept_dt") or "").strip(),
                "filer": str(row.get("flr_nm") or "").strip(),
                "ticker_code": resolved.code,
                "ticker_name": resolved.name,
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            }
        )
    return rows[:limit]


# Filing types where the title alone hides the number that actually moves a
# decision (dilution size, conversion price, buyback size, the earnings
# surprise). disclosure_events (tradingagents/harness/prompts.py) otherwise
# only ever sees report_nm from list.json. Matched as a substring of report_nm
# so amendment suffixes like "(정정)" still match.
_BODY_WORTHY_REPORT_KEYWORDS = (
    "전환사채권발행결정",
    "신주인수권부사채권발행결정",
    "교환사채권발행결정",
    "유상증자결정",
    "무상증자결정",
    "자기주식취득결정",
    "자기주식처분결정",
    "영업(잠정)실적",
    "의무보유",
    "보호예수",
    "최대주주변경",
)


def _is_body_worthy(report_name: str) -> bool:
    return any(keyword in report_name for keyword in _BODY_WORTHY_REPORT_KEYWORDS)


def get_disclosures_with_bodies(
    ticker: Annotated[str, "Korean 6-digit ticker symbol"],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"] = None,
    *,
    days: int = 45,
    limit: int = 10,
    max_bodies: int = 3,
) -> str:
    """Recent DART disclosure titles plus body numbers for the filings that
    actually move a decision.

    This is the context builder for the harness's ``disclosure_events`` prompt
    (context key ``disclosures``). It must never raise into the pipeline: a
    body that fails to fetch or parse costs that one filing a one-line note,
    not the whole title list (same fail-closed rule as
    ``tradingagents.dataflows.deadline`` — a step with a fallback has to take
    it). The title list itself can still raise (e.g. missing DART_API_KEY,
    unsupported ticker); callers that assemble harness context should expect
    that and catch it the same way they already catch other vendor errors.
    """

    rows = list_recent_disclosures(ticker, days=days, limit=limit, curr_date=curr_date)
    if not rows:
        return "- No recent disclosures found."

    lines = [f"- {row['filed_at']} | {row['report_name']} | {row['receipt_no']}" for row in rows]

    bodies_fetched = 0
    for row in rows:
        if bodies_fetched >= max_bodies:
            break
        if not _is_body_worthy(row["report_name"]):
            continue
        bodies_fetched += 1
        try:
            body = get_disclosure_body(row["receipt_no"])
        except Exception as exc:  # fail closed: titles above stay intact
            lines.append(
                f"- body unavailable for {row['receipt_no']} ({row['report_name']}): {exc.__class__.__name__}"
            )
            continue
        lines.append("")
        lines.append(f"## Body: {row['report_name']} ({row['receipt_no']}, {row['filed_at']})")
        lines.append(body)
    return "\n".join(lines)


def get_disclosure_body(rcept_no: str, *, max_rows: int = 80, max_cell_chars: int = 200) -> str:
    """Flatten a DART filing body (``document.xml``) to "label | value" rows.

    ``document.xml`` is a zip; the member inside is DART's own dart4 XML
    (tables built from TABLE/TR/TD/TE/TU tags) for most filing types, or plain
    HTML ``<table>`` for 공정공시 preliminary-earnings filings. markitdown does
    not recognize the dart4 schema and emits the raw tags back out (see
    jobs/2026-11-06-trading-repo-review/poc-dart/RESULT.md in the production
    hub repo); a stdlib html.parser/ElementTree walk of the rows does not have
    that problem and needs no new dependency.

    Cached on disk next to the corp-code cache, keyed by rcept_no: an accepted
    filing's body does not change.
    """

    rcept_no = str(rcept_no).strip()
    if not rcept_no:
        return "(no receipt number given)"

    cache_path = _disclosure_body_cache_path(rcept_no)
    if cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8")
        except OSError:
            pass  # fall through and refetch rather than fail on a stale/locked cache file

    raw = _request_binary("document.xml", {"rcept_no": rcept_no})

    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.namelist()
            if not members:
                result = "(disclosure body empty: no files in archive)"
            else:
                body_bytes = archive.read(members[0])
                result = _flatten_filing_body(body_bytes, max_rows=max_rows, max_cell_chars=max_cell_chars)
    except Exception as exc:  # malformed zip/xml must not raise into the harness
        result = f"(disclosure body parse failed: {exc.__class__.__name__})"

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(result, encoding="utf-8")
    except OSError:
        pass  # caching is an optimization, not a requirement
    return result


def _flatten_filing_body(body_bytes: bytes, *, max_rows: int, max_cell_chars: int) -> str:
    # DART re-serves this as UTF-8 even when a filing's own <meta charset>
    # claims euc-kr (observed on 공정공시 영업(잠정)실적 filings); decoding as
    # UTF-8 with replacement matches what the PoC parser found worked for
    # every sample filing.
    text = body_bytes.decode("utf-8", errors="replace")
    looks_like_dart_schema = "<DOCUMENT" in text[:500] and "<TD" in text
    rows = _dart_schema_rows(text) if looks_like_dart_schema else []
    if not rows:
        rows = _html_table_rows(text)

    lines: list[str] = []
    for row in rows[:max_rows]:
        cells = [_truncate_cell(cell, max_cell_chars) for cell in row if cell]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines) if lines else "(no table rows found in filing body)"


_UNESCAPED_AMP = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")


def _strip_ns_tag(tag: str) -> str:
    return tag.split("}")[-1]


def _dart_schema_rows(text: str) -> list[list[str]]:
    """Walk TABLE>TR rows of DART's own schema, pairing TD/TH labels with TE/TU values.

    DART's XML is sometimes not well-formed in practice: free text (an ENG=
    attribute, a company name) can carry a bare '&' that xml.etree rejects
    outright. Retried once with bare ampersands re-escaped before giving up.
    """

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        try:
            root = ET.fromstring(_UNESCAPED_AMP.sub("&amp;", text))
        except ET.ParseError:
            return []

    rows: list[list[str]] = []
    for element in root.iter():
        if _strip_ns_tag(element.tag) != "TR":
            continue
        cells = [c for c in element if _strip_ns_tag(c.tag) in ("TD", "TH", "TE", "TU")]
        values = ["".join(c.itertext()).strip() for c in cells]
        values = [value for value in values if value]
        if values:
            rows.append(values)

    # Free-text paragraphs (e.g. 의무보유/락업 terms live in prose, not a cell).
    for element in root.iter():
        if _strip_ns_tag(element.tag) == "P":
            value = "".join(element.itertext()).strip()
            if value:
                rows.append([value])
    return rows


class _TableRowParser(HTMLParser):
    """Minimal stdlib HTML <table> row extractor for the 공정공시 earnings filings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _html_table_rows(text: str) -> list[list[str]]:
    parser = _TableRowParser()
    try:
        parser.feed(text)
    except Exception:
        return []
    return [row for row in parser.rows if any(row)]


def _truncate_cell(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def get_corp_code(stock_code: str) -> str:
    if stock_code in _COMMON_CORP_CODES:
        return _COMMON_CORP_CODES[stock_code]

    cache = _corp_code_cache_path()
    if cache.exists():
        mapping = json.loads(cache.read_text(encoding="utf-8"))
    else:
        mapping = _download_corp_code_mapping()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

    corp_code = mapping.get(stock_code)
    if not corp_code:
        raise VendorUnavailableError(f"DART corp code not found for {stock_code}")
    return corp_code


def _financial_statement(ticker: str, curr_date: str | None, freq: str, sj_div: str, title: str) -> str:
    resolved = _require_supported(ticker)
    corp_code = get_corp_code(resolved.code)
    year, report_code = _report_context(curr_date, freq)
    payload = _request_json(
        "fnlttSinglAcntAll.json",
        {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
            "fs_div": "CFS",
        },
    )
    rows = [row for row in payload.get("list", []) if row.get("sj_div") == sj_div]
    if not rows:
        label = _REPORT_CODE_LABELS.get(report_code, report_code)
        return f"No DART {title} rows found for {resolved.name} ({resolved.code}) in {year} {label}"
    lines = [
        f"# DART {title} for {resolved.name} ({resolved.code})",
        f"# Business year: {year}",
        f"# Report: {_REPORT_CODE_LABELS.get(report_code, report_code)}",
        "",
    ]
    for row in rows[:30]:
        lines.append(
            f"- {row.get('account_nm')}: current={row.get('thstrm_amount', 'n/a')}, "
            f"previous={row.get('frmtrm_amount', 'n/a')}"
        )
    return "\n".join(lines)


def _recent_disclosures(corp_code: str, curr_date: str | None, *, days: int, limit: int) -> list[str]:
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d") if curr_date else datetime.now()
    start_dt = end_dt - timedelta(days=days)
    payload = _request_json(
        "list.json",
        {
            "corp_code": corp_code,
            "bgn_de": start_dt.strftime("%Y%m%d"),
            "end_de": end_dt.strftime("%Y%m%d"),
            "page_count": str(limit),
        },
    )
    rows = payload.get("list", [])
    if not rows:
        return ["- No recent disclosures found."]
    return [
        f"- {row.get('rcept_dt')} | {row.get('report_nm')} | {row.get('rcept_no')}"
        for row in rows[:limit]
    ]


def _download_corp_code_mapping() -> dict[str, str]:
    api_key = _api_key()
    response = requests.get(f"{_BASE_URL}/corpCode.xml", params={"crtfc_key": api_key}, timeout=20)
    response.raise_for_status()
    with ZipFile(BytesIO(response.content)) as archive:
        xml_bytes = archive.read("CORPCODE.xml")
    root = ET.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for node in root.findall("list"):
        stock_code = (node.findtext("stock_code") or "").strip()
        corp_code = (node.findtext("corp_code") or "").strip()
        if stock_code and corp_code:
            mapping[stock_code] = corp_code
    return mapping


def _request_binary(endpoint: str, params: dict) -> bytes:
    """Like ``_request_json`` but for binary endpoints (``document.xml`` is a zip).

    requests' own ``HTTPError`` message embeds the full request URL, which
    carries ``crtfc_key`` in the query string — letting that propagate would
    leak the key into logs or a result string. The exception is swallowed and
    replaced with one that names only the endpoint and exception class.
    """

    api_key = _api_key()
    payload = {"crtfc_key": api_key, **params}
    try:
        response = requests.get(f"{_BASE_URL}/{endpoint}", params=payload, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise VendorUnavailableError(f"OpenDART {endpoint} request failed: {exc.__class__.__name__}") from None
    return response.content


def _request_json(endpoint: str, params: dict) -> dict:
    api_key = _api_key()
    payload = {"crtfc_key": api_key, **params}
    response = requests.get(f"{_BASE_URL}/{endpoint}", params=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    status = data.get("status")
    if status and status not in {"000", "013"}:
        message = data.get("message", "Unknown OpenDART error")
        raise RuntimeError(f"OpenDART {endpoint} failed: {status} {message}")
    return data


def _api_key() -> str:
    api_key = os.getenv("DART_API_KEY") or os.getenv("OPEN_DART_API_KEY")
    if not api_key:
        raise VendorUnavailableError("DART_API_KEY is required")
    return api_key


def _require_supported(ticker: str):
    if not is_kr_ticker(ticker):
        raise VendorUnavailableError(f"DART only supports Korean 6-digit tickers: {ticker!r}")
    return resolve_kr_ticker(ticker, lookup_pykrx=False)


def _business_year(curr_date: str | None) -> int:
    if not curr_date:
        return datetime.now().year - 1
    dt = datetime.strptime(curr_date, "%Y-%m-%d")
    return dt.year - 1


def _report_context(curr_date: str | None, freq: str | None) -> tuple[int, str]:
    normalized = (freq or "annual").strip().lower()
    if normalized in {"annual", "yearly", "y"}:
        return _business_year(curr_date), "11011"

    dt = datetime.strptime(curr_date, "%Y-%m-%d") if curr_date else datetime.now()
    if normalized in {"q1", "1q", "first_quarter"}:
        return dt.year, "11013"
    if normalized in {"half", "half_year", "semiannual", "semi-annual", "2q"}:
        return dt.year, "11012"
    if normalized in {"q3", "3q", "third_quarter"}:
        return dt.year, "11014"
    if normalized in {"quarterly", "quarter", "latest"}:
        if dt.month >= 11:
            return dt.year, "11014"
        if dt.month >= 8:
            return dt.year, "11012"
        if dt.month >= 5:
            return dt.year, "11013"
        return dt.year - 1, "11011"

    raise ValueError("freq must be annual, quarterly, q1, half_year, or q3")


def _dart_cache_root() -> Path:
    base = os.getenv("TRADINGAGENTS_CACHE_DIR")
    if base:
        return Path(base).expanduser() / "dart"
    return Path.home() / ".tradingagents" / "cache" / "dart"


def _corp_code_cache_path() -> Path:
    return _dart_cache_root() / "corp_codes.json"


def _disclosure_body_cache_path(rcept_no: str) -> Path:
    safe_name = re.sub(r"[^0-9A-Za-z_-]", "_", rcept_no)
    return _dart_cache_root() / "bodies" / f"{safe_name}.txt"

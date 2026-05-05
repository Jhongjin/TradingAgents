"""OpenDART disclosure and financial-statement vendor."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from io import BytesIO
from typing import Annotated

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


def _corp_code_cache_path() -> Path:
    base = os.getenv("TRADINGAGENTS_CACHE_DIR")
    if base:
        return Path(base).expanduser() / "dart" / "corp_codes.json"
    return Path.home() / ".tradingagents" / "cache" / "dart" / "corp_codes.json"

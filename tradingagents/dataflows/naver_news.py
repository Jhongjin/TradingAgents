"""Naver Search API news vendor for Korean market analysis."""

from __future__ import annotations

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import os
import re
from typing import Annotated

import requests

from .errors import VendorUnavailableError
from .kr_tickers import is_kr_ticker, resolve_kr_ticker

_API_URL = "https://openapi.naver.com/v1/search/news.json"
_TAG_RE = re.compile(r"<[^>]+>")


def get_news(
    ticker: Annotated[str, "Korean ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    resolved = resolve_kr_ticker(ticker, lookup_pykrx=False) if is_kr_ticker(ticker) else None
    if resolved is None:
        raise VendorUnavailableError(f"Naver news vendor is only the primary vendor for Korean tickers: {ticker!r}")
    query = f"{resolved.name} {resolved.code} 주가 실적 공시"
    return _search_news(query, start_date=start_date, end_date=end_date, limit=10)


def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    query = "한국 증시 코스피 코스닥 환율 금리 반도체 수출"
    return _search_news(
        query,
        start_date=start_dt.strftime("%Y-%m-%d"),
        end_date=curr_date,
        limit=limit,
        title="Korean macro and market news",
    )


def _search_news(
    query: str,
    *,
    start_date: str,
    end_date: str,
    limit: int,
    title: str | None = None,
) -> str:
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise VendorUnavailableError("NAVER_CLIENT_ID and NAVER_CLIENT_SECRET are required")

    response = requests.get(
        _API_URL,
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
        params={
            "query": query,
            "display": min(max(limit * 2, 10), 100),
            "sort": "date",
        },
        verify=_requests_verify_setting(),
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    filtered = _filter_by_date(items, start_date, end_date)[:limit]
    if not filtered:
        return f"No Naver news found for query '{query}' between {start_date} and {end_date}"

    lines = [f"# {title or 'Naver news'}", f"# Query: {query}", f"# Date range: {start_date} to {end_date}", ""]
    for item in filtered:
        article_title = _clean_html(item.get("title", ""))
        description = _clean_html(item.get("description", ""))
        pub_date = item.get("pubDate", "")
        link = item.get("originallink") or item.get("link", "")
        lines.append(f"- {pub_date} | {article_title} | {description} | {link}")
    return "\n".join(lines)


def _filter_by_date(items: list[dict], start_date: str, end_date: str) -> list[dict]:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    filtered = []
    for item in items:
        pub_date = item.get("pubDate")
        if not pub_date:
            filtered.append(item)
            continue
        try:
            parsed = parsedate_to_datetime(pub_date).date()
        except Exception:
            filtered.append(item)
            continue
        if start <= parsed <= end:
            filtered.append(item)
    return filtered


def _clean_html(value: str) -> str:
    text = _TAG_RE.sub("", value)
    return (
        text.replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def _requests_verify_setting() -> bool | str:
    """Return SSL verification settings for Naver requests.

    Keep verification enabled by default. For Windows or corporate-network
    environments with a custom root certificate, set
    TRADINGAGENTS_HTTP_CA_BUNDLE or NAVER_CA_BUNDLE to a trusted bundle path.
    """

    ca_bundle = os.getenv("TRADINGAGENTS_HTTP_CA_BUNDLE") or os.getenv("NAVER_CA_BUNDLE")
    if ca_bundle:
        return ca_bundle
    verify = os.getenv("TRADINGAGENTS_HTTP_VERIFY_SSL", "true").strip().lower()
    return verify not in {"0", "false", "no"}

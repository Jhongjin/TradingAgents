"""SEO helpers for the public TradingAgents Korea site."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Iterable


DEFAULT_SITEMAP_TICKERS = (
    "005930",
    "000660",
    "035420",
    "035720",
    "051910",
    "005380",
    "068270",
    "005490",
)
FEATURE_DETAIL_PATHS = (
    "/features/research",
    "/features/member-workspace",
    "/features/outcomes",
)
GOOGLE_ADSENSE_SELLER_DOMAIN = "google.com"
GOOGLE_ADSENSE_CERTIFICATION_AUTHORITY_ID = "f08c47fec0942fa0"


def normalize_site_base_url(value: str | None = None) -> str | None:
    raw = value if value is not None else os.getenv("TRADINGAGENTS_SITE_BASE_URL")
    if not raw:
        return None
    cleaned = raw.strip().rstrip("/")
    if not cleaned:
        return None
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError("site base URL must include http:// or https://")
    return cleaned


def canonical_url(path: str, *, site_base_url: str | None = None) -> str:
    base = normalize_site_base_url(site_base_url)
    normalized_path = path if path.startswith("/") else f"/{path}"
    if base is None:
        return normalized_path
    return f"{base}{normalized_path}"


def stock_canonical_url(ticker: str, *, site_base_url: str | None = None) -> str:
    return canonical_url(f"/stocks/{ticker}", site_base_url=site_base_url)


def build_robots_txt(*, site_base_url: str | None = None) -> str:
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /api/",
        "Disallow: /member",
        "Disallow: /mypage",
        "Disallow: /admin",
    ]
    sitemap_url = canonical_url("/sitemap.xml", site_base_url=site_base_url)
    if sitemap_url.startswith("http"):
        lines.append(f"Sitemap: {sitemap_url}")
    return "\n".join(lines) + "\n"


def build_ads_txt(
    *,
    ads_txt: str | None = None,
    adsense_publisher_id: str | None = None,
) -> str:
    custom_ads_txt = ads_txt if ads_txt is not None else os.getenv("TRADINGAGENTS_ADS_TXT")
    if custom_ads_txt and custom_ads_txt.strip():
        return custom_ads_txt.replace("\\n", "\n").strip() + "\n"

    publisher_id = normalize_adsense_publisher_id(adsense_publisher_id)
    if publisher_id:
        return (
            f"{GOOGLE_ADSENSE_SELLER_DOMAIN}, {publisher_id}, DIRECT, "
            f"{GOOGLE_ADSENSE_CERTIFICATION_AUTHORITY_ID}\n"
        )
    return "# ads.txt is not configured.\n"


def normalize_adsense_publisher_id(value: str | None = None) -> str | None:
    raw = value if value is not None else os.getenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID")
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("ca-pub-"):
        cleaned = cleaned.removeprefix("ca-")
    if not re.fullmatch(r"pub-\d{16}", cleaned):
        raise ValueError("AdSense publisher ID must look like pub-0000000000000000")
    return cleaned


def build_sitemap_xml(
    *,
    site_base_url: str | None = None,
    tickers: Iterable[str] | None = None,
    generated_date: str | None = None,
) -> str:
    base = normalize_site_base_url(site_base_url)
    if base is None:
        raise ValueError("site base URL is required for sitemap.xml")

    date_value = generated_date or datetime.utcnow().date().isoformat()
    urls = [
        (canonical_url("/", site_base_url=base), "daily", "1.0"),
        (canonical_url("/analyses", site_base_url=base), "hourly", "0.8"),
    ]
    urls.extend((canonical_url(path, site_base_url=base), "weekly", "0.7") for path in FEATURE_DETAIL_PATHS)
    urls.extend(
        (stock_canonical_url(ticker, site_base_url=base), "daily", "0.7")
        for ticker in _sitemap_tickers(tickers)
    )

    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for url, changefreq_value, priority_value in urls:
        item = ET.SubElement(urlset, "url")
        loc = ET.SubElement(item, "loc")
        loc.text = url
        lastmod = ET.SubElement(item, "lastmod")
        lastmod.text = date_value
        changefreq = ET.SubElement(item, "changefreq")
        changefreq.text = changefreq_value
        priority = ET.SubElement(item, "priority")
        priority.text = priority_value
    return ET.tostring(urlset, encoding="unicode", xml_declaration=True)


def sitemap_tickers_from_env() -> tuple[str, ...]:
    value = os.getenv("TRADINGAGENTS_SITEMAP_TICKERS", "")
    if not value.strip():
        return DEFAULT_SITEMAP_TICKERS
    return _sitemap_tickers(value.split(","))


def _sitemap_tickers(tickers: Iterable[str] | None) -> tuple[str, ...]:
    source = tickers or DEFAULT_SITEMAP_TICKERS
    cleaned = []
    seen = set()
    for raw in source:
        ticker = str(raw).strip()
        if not ticker or ticker in seen:
            continue
        if ticker.isdigit() and len(ticker) == 6:
            cleaned.append(ticker)
            seen.add(ticker)
    return tuple(cleaned)

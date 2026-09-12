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
    "/features/methodology",
)
POLICY_PAGE_PATHS = (
    "/privacy",
    "/terms",
    "/disclaimer",
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


AI_CRAWLERS = (
    # training corpora, AI search indexes, and on-demand fetchers; citations need all three
    "GPTBot", "OAI-SearchBot", "ChatGPT-User",
    "ClaudeBot", "Claude-SearchBot", "Claude-User",
    "PerplexityBot", "Perplexity-User",
    "Google-Extended", "Applebot-Extended", "CCBot",
    "Yeti",  # Naver
)
PRIVATE_PATHS = ("/api/", "/member", "/mypage", "/admin", "/billing", "/lab/")


def build_robots_txt(*, site_base_url: str | None = None) -> str:
    """Allow every crawler (including AI search/fetch agents) on public pages; keep member and API paths out."""

    lines = ["User-agent: *", "Allow: /"]
    lines.extend(f"Disallow: {path}" for path in PRIVATE_PATHS)
    for agent in AI_CRAWLERS:
        lines.append("")
        lines.append(f"User-agent: {agent}")
        lines.append("Allow: /")
        lines.extend(f"Disallow: {path}" for path in PRIVATE_PATHS)
    sitemap_url = canonical_url("/sitemap.xml", site_base_url=site_base_url)
    if sitemap_url.startswith("http"):
        lines.append("")
        lines.append(f"Sitemap: {sitemap_url}")
    return "\n".join(lines) + "\n"


def build_llms_txt(*, site_base_url: str | None = None, latest_run_date: str | None = None) -> str:
    """Markdown guide for generative engines: what the site is the primary source for."""

    def link(path: str) -> str:
        return canonical_url(path, site_base_url=site_base_url)

    updated = latest_run_date or datetime.utcnow().date().isoformat()
    return f"""# TradingAgents Korea

> 코스피200·코스닥150 종목을 매일 아침 규칙으로 거르고, 강세·약세 AI 토론으로 확인한 뒤, 모의투자로 5·20거래일 성과를 검증해 공개하는 한국 주식 리서치 도구입니다. 실계좌 주문은 없으며 투자 조언이 아닙니다.

## 핵심 페이지
- [오늘의 선정 종목]({link('/')}): 최근 선별 실행의 통과 종목, 규칙 점수, 20일 예상 수익률, AI 토론 판정, 모의 주문 내역
- [선별 기록]({link('/harness')}): 날짜별 선별 실행 전체 기록 (대상 종목 수, 후보, 통과, 모의 주문, 검증 결과)
- [성과 검증]({link('/outcomes')}): 선정 종목의 5거래일·20거래일 수익률과 지수 대비 초과수익
- [AI 리포트]({link('/analyses')}): 종목별 AI 분석 리포트
- [분석 기준]({link('/features/methodology')}): 선별 규칙, 예측 모델, 토론 절차, 리스크 한도
- [30초 안내]({link('/start')}): 이 사이트가 무엇을 하는지, 무엇이 열려 있는지, 가입하면 무엇이 더해지는지
- [{pricing_line_label()}]({link('/pricing')}): {pricing_line_text()}

## 데이터 정책
- 출처: pykrx(KRX 시세), Naver 금융, DART 공시, 한국투자증권 Open API(모의투자). 페이지마다 출처와 기준 시각을 표시합니다.
- 갱신: 평일 07:50 선별, 10:05 모의 주문, 16:40 재검토. 5·20거래일 뒤 성과 확정. 최근 갱신 {updated}.
- 자체 산출 지표: 규칙 점수(추세·모멘텀·거래대금 합산), 20일 상승 확률(TimesFM), AI 토론 신뢰도, 지수 대비 초과수익.
- 인용 시 표기: TradingAgents Korea ({link('/')})
- JSON: {link('/api/harness/runs')}, {link('/api/harness/outcomes')}
"""


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


def adsense_head(publisher_id: str | None = None, *, token_storage_key: str = "tradingagents.member.access_token") -> str:
    """Google's loader, plus the switch that keeps a paying member ad-free.

    The 데일리 패스 plan promises 광고 없음, and the page HTML is public and
    cached, so the decision cannot be made server-side. Ad requests start
    paused; the browser resumes them only after it confirms the reader is not
    on a paid plan. The loader itself is always present, which is what Google's
    verification looks for.
    """

    try:
        resolved = normalize_adsense_publisher_id(publisher_id)
    except ValueError:
        return ""
    if not resolved:
        return ""
    client = f"ca-{resolved}"
    return (
        "<script>window.adsbygoogle=window.adsbygoogle||[];window.adsbygoogle.pauseAdRequests=1;</script>"
        f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={client}" crossorigin="anonymous"></script>'
        "<script>(function(){var K='" + token_storage_key + "';function resume(){try{window.adsbygoogle.pauseAdRequests=0;}catch(e){}}"
        "var t='';try{t=localStorage.getItem(K)||sessionStorage.getItem(K)||'';}catch(e){}"
        "if(!t){resume();return;}"
        "fetch('/api/billing/me',{headers:{'Authorization':'Bearer '+t}}).then(function(r){return r.ok?r.json():null;}).then(function(d){"
        "var a=d&&d.access;var paid=Boolean(a&&a.status==='active'&&a.plan&&a.plan.id!=='free');"
        "if(!paid){resume();}}).catch(resume);})();</script>"
    )


def pricing_line_label() -> str:
    from .billing import paid_plans_enabled

    return "요금제" if paid_plans_enabled() else "무료 안내"


def pricing_line_text() -> str:
    from .billing import paid_plans_enabled

    if paid_plans_enabled():
        return "무료 · 데일리 패스(월 10,000원) · 프로(월 30,000원)"
    return "모든 기능 무료 · 광고로 운영 · 실계좌 주문 없음"


def ad_unit(*, slot_env: str = "TRADINGAGENTS_ADSENSE_SLOT_INFEED", css_class: str = "ad-unit") -> str:
    """One responsive display unit, or nothing when no slot is configured.

    Auto ads already run from the page head. This is for the one deliberate
    placement per page, below the hero, where a unit does not push the table
    the reader came for below the fold.
    """

    try:
        publisher = normalize_adsense_publisher_id()
    except ValueError:
        return ""
    slot = (os.getenv(slot_env) or "").strip()
    if not publisher or not slot.isdigit():
        return ""
    return (
        f'<div class="{css_class}" style="margin: 14px 0;"><ins class="adsbygoogle" style="display:block" data-ad-client="ca-{publisher}" '
        f'data-ad-slot="{slot}" data-ad-format="auto" data-full-width-responsive="true"></ins>'
        "<script>(window.adsbygoogle=window.adsbygoogle||[]).push({});</script></div>"
    )


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
    analysis_paths: Iterable[str] | None = None,
    harness_paths: Iterable[str] | None = None,
    history_paths: Iterable[str] | None = None,
    generated_date: str | None = None,
) -> str:
    base = normalize_site_base_url(site_base_url)
    if base is None:
        raise ValueError("site base URL is required for sitemap.xml")

    date_value = generated_date or datetime.utcnow().date().isoformat()
    urls = [
        (canonical_url("/", site_base_url=base), "daily", "1.0"),
        (canonical_url("/harness", site_base_url=base), "daily", "0.9"),
        (canonical_url("/paper", site_base_url=base), "daily", "0.85"),
        (canonical_url("/outcomes", site_base_url=base), "hourly", "0.8"),
        (canonical_url("/analyses", site_base_url=base), "hourly", "0.8"),
        (canonical_url("/features", site_base_url=base), "weekly", "0.8"),
        (canonical_url("/start", site_base_url=base), "monthly", "0.8"),
        (canonical_url("/pricing", site_base_url=base), "weekly", "0.6"),
    ]
    urls.extend((canonical_url(path, site_base_url=base), "weekly", "0.7") for path in _sitemap_harness_paths(harness_paths))
    urls.extend((canonical_url(path, site_base_url=base), "daily", "0.7") for path in _sitemap_prefixed_paths(history_paths, "/stocks/", "/history"))
    urls.extend(
        (canonical_url(path, site_base_url=base), "daily", "0.7")
        for path in _sitemap_analysis_paths(analysis_paths)
    )
    urls.extend((canonical_url(path, site_base_url=base), "weekly", "0.7") for path in FEATURE_DETAIL_PATHS)
    urls.extend((canonical_url(path, site_base_url=base), "monthly", "0.5") for path in POLICY_PAGE_PATHS)
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


def _sitemap_analysis_paths(paths: Iterable[str] | None) -> tuple[str, ...]:
    cleaned = []
    seen = set()
    for raw in paths or ():
        path = str(raw).strip()
        if not path.startswith("/analyses/") or path in seen:
            continue
        cleaned.append(path)
        seen.add(path)
    return tuple(cleaned)


def _sitemap_harness_paths(paths: Iterable[str] | None) -> tuple[str, ...]:
    cleaned = []
    seen = set()
    for raw in paths or ():
        path = str(raw).strip()
        if not path.startswith("/harness/") or path in seen:
            continue
        cleaned.append(path)
        seen.add(path)
    return tuple(cleaned)


INDEXNOW_KEY_ENV = "TRADINGAGENTS_INDEXNOW_KEY"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"


def indexnow_key(value: str | None = None) -> str | None:
    raw = (value if value is not None else os.getenv(INDEXNOW_KEY_ENV, "")).strip()
    if not raw:
        return None
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", raw):
        raise ValueError("IndexNow key must be 8-128 letters, digits, or dashes")
    return raw


def indexnow_key_location(key: str, *, site_base_url: str | None = None) -> str:
    # The key file must sit at the site root: IndexNow only accepts URLs under the
    # key file's directory, so a /indexnow/ subfolder would reject every page.
    return canonical_url(f"/{key}.txt", site_base_url=site_base_url)


def submit_indexnow(paths: Iterable[str], *, site_base_url: str | None = None, key: str | None = None, transport=None, timeout: float = 10.0) -> dict:
    """Ping IndexNow (Bing, Naver, Yandex consume it) with absolute URLs for ``paths``.

    Never raises: returns ``{"status": "skipped"|"sent"|"failed", ...}`` so callers in
    the harness pipeline cannot be broken by a search-engine outage.
    """

    resolved_key = indexnow_key(key)
    base = normalize_site_base_url(site_base_url)
    urls = []
    seen = set()
    for raw in paths:
        path = str(raw).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        urls.append(canonical_url(path, site_base_url=base))
    if not resolved_key or not base or not urls:
        return {"status": "skipped", "reason": "key, site base URL, and paths are required", "urls": urls}
    host = base.split("://", 1)[1].split("/", 1)[0]
    payload = {"host": host, "key": resolved_key, "keyLocation": indexnow_key_location(resolved_key, site_base_url=base), "urlList": urls[:10000]}
    body = ""
    try:
        if transport is None:
            import json as _json

            import requests

            response = requests.post(
                INDEXNOW_ENDPOINT,
                data=_json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "TradingAgentsKorea/1.0 (+https://agenttrust.kr)"},
                timeout=timeout,
            )
            status_code = response.status_code
            body = (response.text or "")[:300]
        else:
            status_code = int(transport(INDEXNOW_ENDPOINT, payload))
    except Exception as exc:  # network trouble is not fatal
        return {"status": "failed", "error": f"{exc.__class__.__name__}: {exc}", "urls": urls}
    result = {"status": "sent" if status_code in (200, 202) else "failed", "http_status": status_code, "urls": urls}
    if body and status_code not in (200, 202):
        result["response"] = body
    return result


def _sitemap_prefixed_paths(paths: Iterable[str] | None, prefix: str, suffix: str = "") -> tuple[str, ...]:
    cleaned = []
    seen = set()
    for raw in paths or ():
        path = str(raw).strip()
        if not path.startswith(prefix) or (suffix and not path.endswith(suffix)) or path in seen:
            continue
        cleaned.append(path)
        seen.add(path)
    return tuple(cleaned)


VERIFICATION_FILES_ENV = "TRADINGAGENTS_VERIFICATION_FILES"
VERIFICATION_FILE_PATTERN = re.compile(r"^(google[a-z0-9]+\.html|naver[a-z0-9]+\.html|BingSiteAuth\.xml|yandex_[a-z0-9]+\.html)$")


def verification_files(value: str | None = None) -> dict[str, str]:
    """Search-console ownership files served from the site root.

    ``TRADINGAGENTS_VERIFICATION_FILES`` is a JSON object ``{"filename": "content"}``.
    Only well-known verification file names are accepted so the env var can never
    turn into an arbitrary static-file host.
    """

    import json

    raw = value if value is not None else os.getenv(VERIFICATION_FILES_ENV, "")
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError("TRADINGAGENTS_VERIFICATION_FILES must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("TRADINGAGENTS_VERIFICATION_FILES must be a JSON object")
    files = {}
    for name, content in parsed.items():
        name = str(name).strip()
        if VERIFICATION_FILE_PATTERN.match(name) and isinstance(content, str) and content.strip():
            files[name] = content.strip() + "\n"
    return files

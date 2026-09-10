"""Watch the news on positions we already hold.

Picks were checked once, on the morning they were bought. After that only the
price rules watched them, so a position could sit through a disclosure or an
earnings shock until it drifted into the stop. This reads the recent Korean
news for a held name and asks whether something happened that breaks the
reason it was bought.

It only ever produces a reason to close a position. It cannot open one, and a
missing news feed or an unparseable answer means "no signal", never "sell".
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

NewsFetcher = Callable[[str, str, str], str]
RiskChecker = Callable[[str, str, date], tuple[bool, str]]

PROMPT = """당신은 이미 보유한 한국 주식의 악재를 감시하는 리스크 담당자입니다.
아래 뉴스만 근거로, 보유를 중단할 만한 중대한 악재가 있는지 판단하세요.

판단 기준:
- 중대한 악재란 실적 급락, 회계·감사 문제, 대규모 유상증자, 소송·제재, 핵심 사업 중단,
  경영권 분쟁, 상장폐지 위험처럼 매수 근거를 무너뜨리는 사건입니다.
- 단순 주가 하락, 시황 부진, 목표주가 조정, 일반적인 업황 전망은 악재가 아닙니다.
- 뉴스가 없거나 판단이 애매하면 악재가 아니라고 답하세요.

종목: {name}({code})
기준일: {as_of}

## 뉴스
{news}

아래 JSON 형식으로만 답하세요.
{{"material_risk": true 또는 false, "headline": "근거가 된 사건 한 줄", "confidence": 0.0~1.0}}
"""


def _parse(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_news_risk_checker(
    llm: Callable[[str], str],
    *,
    news_fetcher: NewsFetcher | None = None,
    lookback_days: int = 3,
    min_confidence: float = 0.6,
) -> RiskChecker:
    """Return ``checker(code, name, as_of) -> (should_exit, reason)``."""

    def _fetch(code: str, start: str, end: str) -> str:
        if news_fetcher is not None:
            return news_fetcher(code, start, end)
        from tradingagents.dataflows.naver_news import get_news

        return get_news(code, start, end)

    def _check(code: str, name: str, as_of: date) -> tuple[bool, str]:
        end = as_of if isinstance(as_of, date) else datetime.now().date()
        start = end - timedelta(days=max(lookback_days, 1))
        try:
            news = _fetch(code, start.isoformat(), end.isoformat())
        except Exception:
            return False, ""  # no feed is not a sell signal
        if not str(news or "").strip():
            return False, ""
        try:
            raw = llm(PROMPT.format(name=name or code, code=code, as_of=end.isoformat(), news=str(news)[:6000]))
        except Exception:
            return False, ""
        payload = _parse(raw)
        if not payload.get("material_risk"):
            return False, ""
        try:
            confidence = float(payload.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < min_confidence:
            return False, ""
        headline = " ".join(str(payload.get("headline") or "").split())[:120]
        return True, headline or "보유 근거를 무너뜨리는 악재가 확인되었습니다"

    return _check

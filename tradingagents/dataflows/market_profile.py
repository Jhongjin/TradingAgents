"""Market-profile helpers for prompts, benchmarks, and defaults."""

from __future__ import annotations

from dataclasses import dataclass

from .kr_tickers import is_kr_ticker, resolve_kr_ticker


@dataclass(frozen=True)
class MarketProfile:
    market: str
    currency: str
    timezone: str
    regular_session: str
    benchmark_symbol: str


US_MARKET_PROFILE = MarketProfile(
    market="US",
    currency="USD",
    timezone="America/New_York",
    regular_session="09:30-16:00",
    benchmark_symbol="SPY",
)


def get_market_profile(ticker: str, config: dict | None = None) -> MarketProfile:
    config = config or {}
    if is_kr_ticker(ticker):
        resolved = resolve_kr_ticker(ticker, lookup_pykrx=False)
        kr_cfg = config.get("korea", {}) if isinstance(config.get("korea"), dict) else {}
        benchmark_by_market = kr_cfg.get("benchmark_by_market", {})
        benchmark = benchmark_by_market.get(resolved.market, resolved.benchmark_symbol)
        return MarketProfile(
            market="KR",
            currency="KRW",
            timezone="Asia/Seoul",
            regular_session="09:00-15:30",
            benchmark_symbol=benchmark,
        )
    return US_MARKET_PROFILE

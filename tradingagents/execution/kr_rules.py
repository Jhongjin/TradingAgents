"""Korean market paper-execution rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from math import ceil, floor
from zoneinfo import ZoneInfo

from .models import OrderSide
from tradingagents.dataflows.kr_tickers import resolve_kr_ticker


_TOTAL_SELL_TAX_RATE_BY_MARKET = {
    # 2026 effective sell-side transaction cost for listed Korean stocks:
    # securities transaction tax plus the KOSPI rural special tax where applicable.
    "KOSPI": 0.0020,
    "KOSDAQ": 0.0020,
    "KONEX": 0.0010,
    "UNKNOWN": 0.0020,
}


@dataclass(frozen=True)
class KoreaTradingRules:
    timezone: str = "Asia/Seoul"
    regular_open: time = time(9, 0)
    regular_close: time = time(15, 30)
    daily_limit_pct: float = 0.30

    def is_regular_session(self, when: datetime) -> bool:
        if when.tzinfo is None:
            when = when.replace(tzinfo=ZoneInfo(self.timezone))
        local = when.astimezone(ZoneInfo(self.timezone))
        if local.weekday() >= 5:
            return False
        return self.regular_open <= local.time() <= self.regular_close

    def tick_size(self, price: float) -> int:
        if price < 0:
            raise ValueError("price cannot be negative")
        if price < 2_000:
            return 1
        if price < 5_000:
            return 5
        if price < 20_000:
            return 10
        if price < 50_000:
            return 50
        if price < 200_000:
            return 100
        if price < 500_000:
            return 500
        return 1_000

    def round_price(self, price: float, side: OrderSide | None = None) -> int:
        tick = self.tick_size(price)
        if side == OrderSide.BUY:
            return int(ceil(price / tick) * tick)
        if side == OrderSide.SELL:
            return int(floor(price / tick) * tick)
        return int(round(price / tick) * tick)

    def limit_price(self, previous_close: float, side: OrderSide) -> int:
        if previous_close <= 0:
            raise ValueError("previous_close must be positive")
        lower, upper = self.price_limits(previous_close)
        return upper if side == OrderSide.BUY else lower

    def price_limits(self, previous_close: float) -> tuple[int, int]:
        if previous_close <= 0:
            raise ValueError("previous_close must be positive")
        tick = self.tick_size(previous_close)
        limit_width = floor((previous_close * self.daily_limit_pct) / tick) * tick
        return int(max(previous_close - limit_width, 0)), int(previous_close + limit_width)

    def transaction_tax_rate(self, ticker_or_market: str) -> float:
        market = ticker_or_market.strip().upper()
        if market not in _TOTAL_SELL_TAX_RATE_BY_MARKET:
            try:
                market = resolve_kr_ticker(ticker_or_market, lookup_pykrx=False).market
            except ValueError:
                market = "UNKNOWN"
        return _TOTAL_SELL_TAX_RATE_BY_MARKET.get(market, _TOTAL_SELL_TAX_RATE_BY_MARKET["UNKNOWN"])

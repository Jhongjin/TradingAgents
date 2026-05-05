"""Smoke-test the Korean market MVP without invoking an LLM.

The script loads `.env`, checks Korean ticker resolution, fetches a short
pykrx OHLCV sample, optionally checks KRX Open API/DART/Naver/KIS when their
keys are present, and runs a KRW paper backtest. It prints statuses only and
never prints secret values.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
from pathlib import Path
import sys

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.dataflows.dart import get_fundamentals
from tradingagents.dataflows.krx_openapi import get_stock as get_krx_stock
from tradingagents.dataflows.kr_tickers import resolve_kr_ticker
from tradingagents.dataflows.naver_news import get_news
from tradingagents.dataflows.pykrx_vendor import get_stock
from tradingagents.execution import BacktestEngine, KISConfig, RiskLimits


def main() -> int:
    load_dotenv(ROOT / ".env")

    ticker = os.getenv("TRADINGAGENTS_KR_SMOKE_TICKER", "005930")
    end = os.getenv("TRADINGAGENTS_KR_SMOKE_END_DATE") or _yesterday()
    start = os.getenv("TRADINGAGENTS_KR_SMOKE_START_DATE") or _days_before(end, 7)

    print(f"[ticker] {ticker}")
    resolved = resolve_kr_ticker(ticker)
    print(f"[resolver] OK {resolved.name} {resolved.code} {resolved.market}")

    ohlcv_text = get_stock(ticker, start, end)
    ohlcv_lines = ohlcv_text.splitlines()
    print(f"[pykrx] OK lines={len(ohlcv_lines)} header={ohlcv_lines[0] if ohlcv_lines else 'empty'}")

    _optional(
        "krx",
        bool(os.getenv("KRX_API_KEY") or os.getenv("KRX_OPENAPI_KEY")),
        lambda: get_krx_stock(ticker, start, end),
    )
    _optional("dart", bool(os.getenv("DART_API_KEY")), lambda: get_fundamentals(ticker, end))
    _optional(
        "naver",
        bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET")),
        lambda: get_news(ticker, start, end),
    )
    _optional(
        "kis",
        bool(os.getenv("KIS_ACCOUNT_NO") or os.getenv("KIS_CANO")),
        _validate_kis_config,
    )

    prices = _price_frame_from_csv_lines(ohlcv_text)
    if prices.empty:
        print("[backtest] SKIP no price rows")
    else:
        decision_date = prices.index[0].date().isoformat()
        result = BacktestEngine(
            initial_cash=10_000_000,
            risk_limits=RiskLimits(max_position_weight=0.25),
            currency="KRW",
        ).run(ticker, prices, {decision_date: "Rating: Buy"})
        print(
            "[backtest] OK "
            f"currency={result.equity_curve.iloc[-1]['currency']} "
            f"final_equity={result.final_equity:.0f} fills={len(result.fills)}"
        )

    return 0


def _optional(name: str, configured: bool, func) -> None:
    if not configured:
        print(f"[{name}] SKIP credentials not configured")
        return
    try:
        text = func()
    except Exception as exc:
        print(f"[{name}] FAIL {type(exc).__name__}: {exc}")
        return
    first_line = text.splitlines()[0] if text.splitlines() else "empty"
    print(f"[{name}] OK lines={len(text.splitlines())} header={first_line}")


def _validate_kis_config() -> str:
    config = KISConfig.from_env()
    config.validate_for_paper()
    return "# KIS config\n- Mode: paper\n- Credential shape: valid"


def _price_frame_from_csv_lines(text: str) -> pd.DataFrame:
    csv_start = None
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("Date,"):
            csv_start = idx
            break
    if csv_start is None:
        return pd.DataFrame()
    from io import StringIO

    frame = pd.read_csv(StringIO("\n".join(lines[csv_start:])))
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame.set_index("Date")


def _yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _days_before(date_text: str, days: int) -> str:
    return (datetime.strptime(date_text, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


if __name__ == "__main__":
    raise SystemExit(main())

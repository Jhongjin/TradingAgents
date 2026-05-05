from unittest.mock import MagicMock, patch

import pandas as pd

from cli.utils import normalize_ticker_symbol
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.dataflows.kr_tickers import (
    benchmark_for_kr_ticker,
    is_kr_ticker,
    normalize_kr_ticker,
    resolve_kr_ticker,
    to_yfinance_symbol,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _price_df(prices):
    return pd.DataFrame({"Close": prices})


def test_kr_ticker_normalization_preserves_leading_zeroes():
    assert normalize_ticker_symbol(" 005930 ") == "005930"
    assert normalize_kr_ticker("005930.KS") == "005930"
    assert is_kr_ticker("005930")


def test_kr_ticker_resolver_known_stock():
    resolved = resolve_kr_ticker("005930")

    assert resolved.code == "005930"
    assert resolved.name == "삼성전자"
    assert resolved.market == "KOSPI"
    assert resolved.yfinance_symbol == "005930.KS"
    assert benchmark_for_kr_ticker("005930") == "^KS11"


def test_kr_ticker_resolver_kosdaq_suffix():
    resolved = resolve_kr_ticker("123456.KQ", lookup_pykrx=False)

    assert resolved.code == "123456"
    assert resolved.market == "KOSDAQ"
    assert to_yfinance_symbol("123456.KQ") == "123456.KQ"


def test_build_instrument_context_for_korean_market():
    context = build_instrument_context("005930")

    assert "삼성전자" in context
    assert "KRW" in context
    assert "DART" in context
    assert "09:00-15:30" in context


def test_fetch_returns_uses_korean_benchmark_for_kr_ticker():
    mock_graph = MagicMock(spec=TradingAgentsGraph)

    with patch("tradingagents.graph.trading_graph.fetch_korean_returns", return_value=(0.02, 0.01, 2)) as mock_fetch:
        with patch("yfinance.Ticker") as mock_ticker_cls:
            raw, alpha, days = TradingAgentsGraph._fetch_returns(mock_graph, "005930", "2026-01-05")

    mock_fetch.assert_called_once_with("005930", "2026-01-05", 5)
    mock_ticker_cls.assert_not_called()
    assert raw == 0.02
    assert alpha == 0.01
    assert days == 2


def test_fetch_returns_falls_back_to_yfinance_when_pykrx_unavailable():
    stock_prices = [70_000.0, 71_000.0, 72_000.0]
    kospi_prices = [2_700.0, 2_710.0, 2_720.0]
    mock_graph = MagicMock(spec=TradingAgentsGraph)
    mock_graph.config = {
        "korea": {
            "benchmark_by_market": {
                "KOSPI": "^KS11",
                "KOSDAQ": "^KQ11",
                "UNKNOWN": "^KS11",
            }
        }
    }

    with patch("tradingagents.graph.trading_graph.fetch_korean_returns", side_effect=RuntimeError("pykrx down")):
        with patch("yfinance.Ticker") as mock_ticker_cls:
            def _make_ticker(sym):
                m = MagicMock()
                m.history.return_value = _price_df(kospi_prices if sym == "^KS11" else stock_prices)
                return m

            mock_ticker_cls.side_effect = _make_ticker
            raw, alpha, days = TradingAgentsGraph._fetch_returns(mock_graph, "005930", "2026-01-05")

    called_symbols = [call.args[0] for call in mock_ticker_cls.call_args_list]
    assert "005930.KS" in called_symbols
    assert "^KS11" in called_symbols
    assert raw is not None and alpha is not None and days == 2

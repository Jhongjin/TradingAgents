import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from cli.utils import normalize_ticker_symbol
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.dataflows.kr_tickers import (
    benchmark_for_kr_ticker,
    is_kr_ticker,
    normalize_kr_ticker,
    resolve_kr_ticker,
    search_kr_tickers,
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


def test_search_kr_tickers_matches_code_and_name_without_network():
    by_name = search_kr_tickers("삼성", lookup_pykrx=False)
    by_code = search_kr_tickers("000", lookup_pykrx=False)

    assert by_name[0].code == "005930"
    assert by_name[0].name == "삼성전자"
    assert any(item.code == "000660" for item in by_code)


def test_search_kr_tickers_matches_rokit_healthcare_aliases_without_network():
    by_name = search_kr_tickers("로킷헬스케어", lookup_pykrx=False)
    by_typo = search_kr_tickers("로켓헬스케어", lookup_pykrx=False)

    assert by_name[0].code == "376900"
    assert by_name[0].name == "로킷헬스케어"
    assert by_name[0].market == "KOSDAQ"
    assert by_typo[0].code == "376900"
    assert by_typo[0].name == "로킷헬스케어"


def test_kr_ticker_resolver_kosdaq_suffix():
    resolved = resolve_kr_ticker("123456.KQ", lookup_pykrx=False)

    assert resolved.code == "123456"
    assert resolved.market == "KOSDAQ"
    assert to_yfinance_symbol("123456.KQ") == "123456.KQ"


def test_kr_ticker_resolver_uses_pykrx_for_unseeded_stock(monkeypatch):
    class FakeStock:
        @staticmethod
        def get_market_ticker_name(code):
            return "테스트헬스"

        @staticmethod
        def get_market_ticker_list(*, market):
            return ["123456"] if market == "KOSDAQ" else []

    monkeypatch.setitem(sys.modules, "pykrx", SimpleNamespace(stock=FakeStock))

    resolved = resolve_kr_ticker("123456")

    assert resolved.code == "123456"
    assert resolved.name == "테스트헬스"
    assert resolved.market == "KOSDAQ"


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

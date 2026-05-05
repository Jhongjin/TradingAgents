"""TradingAgents graph runner adapter for queued analysis requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


GraphFactory = Callable[..., TradingAgentsGraph]


def run_tradingagents_graph_for_request(
    request: Mapping[str, Any],
    *,
    config: dict[str, Any] | None = None,
    selected_analysts: list[str] | None = None,
    graph_factory: GraphFactory = TradingAgentsGraph,
) -> str:
    """Run TradingAgents for one queued analysis request.

    The graph's optional storage hook must persist the completed analysis and
    populate `last_analysis_run_id`. Production workers should pass the same
    durable `DATABASE_URL` config used by the API.
    """

    ticker = str(request["ticker_code"])
    trade_date = _date_string(request["requested_trade_date"])
    graph_config = DEFAULT_CONFIG.copy()
    graph_config.update(config or {})
    graph_config["storage_enabled"] = True

    graph = graph_factory(
        selected_analysts=selected_analysts or ["market", "social", "news", "fundamentals"],
        debug=False,
        config=graph_config,
    )
    graph.propagate(ticker, trade_date)

    analysis_run_id = getattr(graph, "last_analysis_run_id", None)
    if not analysis_run_id:
        raise RuntimeError("TradingAgents graph finished without a persisted analysis_run_id")
    return str(analysis_run_id)


def _date_string(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)

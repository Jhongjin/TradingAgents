"""TradingAgents graph runner adapter for queued analysis requests."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
import os
import tempfile
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
    _configure_worker_write_paths(graph_config, config or {})

    with _worker_write_env(graph_config, config or {}):
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


def _configure_worker_write_paths(graph_config: dict[str, Any], overrides: Mapping[str, Any]) -> None:
    """Keep Vercel worker runs away from read-only home directories."""

    worker_root = os.path.join(tempfile.gettempdir(), "tradingagents", "worker")
    if not overrides.get("results_dir") and not os.getenv("TRADINGAGENTS_RESULTS_DIR"):
        graph_config["results_dir"] = os.path.join(worker_root, "logs")
    if not overrides.get("data_cache_dir") and not os.getenv("TRADINGAGENTS_CACHE_DIR"):
        graph_config["data_cache_dir"] = os.path.join(worker_root, "cache")
    if not overrides.get("memory_log_path") and not os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH"):
        graph_config["memory_log_path"] = os.path.join(worker_root, "memory", "trading_memory.md")


@contextmanager
def _worker_write_env(graph_config: Mapping[str, Any], overrides: Mapping[str, Any]) -> Iterator[None]:
    updates: dict[str, str] = {}
    if overrides.get("data_cache_dir") or not os.getenv("TRADINGAGENTS_CACHE_DIR"):
        updates["TRADINGAGENTS_CACHE_DIR"] = str(graph_config["data_cache_dir"])
    if overrides.get("results_dir") or not os.getenv("TRADINGAGENTS_RESULTS_DIR"):
        updates["TRADINGAGENTS_RESULTS_DIR"] = str(graph_config["results_dir"])
    if overrides.get("memory_log_path") or not os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH"):
        updates["TRADINGAGENTS_MEMORY_LOG_PATH"] = str(graph_config["memory_log_path"])

    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

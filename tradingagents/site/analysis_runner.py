"""TradingAgents graph runner adapter for queued analysis requests."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
import logging
import os
import tempfile
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.storage import StorageRepository

from .paper_simulation_api import build_paper_learning_context_payload


GraphFactory = Callable[..., TradingAgentsGraph]
logger = logging.getLogger(__name__)


def run_tradingagents_graph_for_request(
    request: Mapping[str, Any],
    *,
    config: dict[str, Any] | None = None,
    repo: StorageRepository | None = None,
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
    paper_learning_context = _paper_learning_context(request, repo)
    if paper_learning_context:
        graph_config["paper_learning_context"] = paper_learning_context

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


def _paper_learning_context(request: Mapping[str, Any], repo: StorageRepository | None) -> str:
    """Return anonymous paper-simulation lessons for the requested ticker."""

    if repo is None:
        return ""
    ticker = str(request.get("ticker_code") or "").strip() or None
    try:
        payload = build_paper_learning_context_payload(repo, ticker_code=ticker)
        context_text = str(payload.get("context_text") or "").strip()
        if context_text:
            return context_text
        if ticker:
            payload = build_paper_learning_context_payload(repo, ticker_code=None)
    except Exception as exc:
        logger.info(
            "Paper simulation learning context unavailable for %s: %s",
            ticker or "unknown",
            exc,
        )
        return ""
    return str(payload.get("context_text") or "").strip()


def _date_string(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _configure_worker_write_paths(graph_config: dict[str, Any], overrides: Mapping[str, Any]) -> None:
    """Keep Vercel worker runs away from read-only home directories."""

    worker_root = _worker_root()
    _configure_write_path(
        graph_config,
        overrides,
        config_key="results_dir",
        env_name="TRADINGAGENTS_RESULTS_DIR",
        default_path=os.path.join(worker_root, "logs"),
    )
    _configure_write_path(
        graph_config,
        overrides,
        config_key="data_cache_dir",
        env_name="TRADINGAGENTS_CACHE_DIR",
        default_path=os.path.join(worker_root, "cache"),
    )
    _configure_write_path(
        graph_config,
        overrides,
        config_key="memory_log_path",
        env_name="TRADINGAGENTS_MEMORY_LOG_PATH",
        default_path=os.path.join(worker_root, "memory", "trading_memory.md"),
    )


@contextmanager
def _worker_write_env(graph_config: Mapping[str, Any], overrides: Mapping[str, Any]) -> Iterator[None]:
    updates: dict[str, str] = {}
    for config_key, env_name in (
        ("data_cache_dir", "TRADINGAGENTS_CACHE_DIR"),
        ("results_dir", "TRADINGAGENTS_RESULTS_DIR"),
        ("memory_log_path", "TRADINGAGENTS_MEMORY_LOG_PATH"),
    ):
        desired = str(graph_config[config_key])
        if overrides.get(config_key) or os.getenv(env_name) != desired:
            updates[env_name] = desired

    if _serverless_runtime():
        worker_root = _worker_root()
        worker_home = os.path.join(worker_root, "home")
        updates["HOME"] = worker_home
        updates.setdefault("XDG_CACHE_HOME", os.path.join(worker_root, "xdg-cache"))
        updates.setdefault("MPLCONFIGDIR", os.path.join(worker_root, "matplotlib"))
        updates.setdefault("HF_HOME", os.path.join(worker_root, "hf"))

    _ensure_worker_write_dirs(graph_config, updates)

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


def _worker_root() -> str:
    return os.path.join(tempfile.gettempdir(), "tradingagents", "worker")


def _serverless_runtime() -> bool:
    return any(
        os.getenv(name)
        for name in (
            "VERCEL",
            "VERCEL_ENV",
            "VERCEL_URL",
            "VERCEL_REGION",
            "AWS_LAMBDA_FUNCTION_NAME",
        )
    )


def _configure_write_path(
    graph_config: dict[str, Any],
    overrides: Mapping[str, Any],
    *,
    config_key: str,
    env_name: str,
    default_path: str,
) -> None:
    if overrides.get(config_key):
        return
    env_value = os.getenv(env_name)
    if env_value and not _serverless_runtime():
        graph_config[config_key] = env_value
        return
    graph_config[config_key] = default_path


def _ensure_worker_write_dirs(graph_config: Mapping[str, Any], updates: Mapping[str, str]) -> None:
    for config_key in ("data_cache_dir", "results_dir"):
        os.makedirs(str(graph_config[config_key]), exist_ok=True)
    os.makedirs(os.path.dirname(str(graph_config["memory_log_path"])), exist_ok=True)
    for env_name in ("HOME", "XDG_CACHE_HOME", "MPLCONFIGDIR", "HF_HOME"):
        path = updates.get(env_name)
        if path:
            os.makedirs(path, exist_ok=True)

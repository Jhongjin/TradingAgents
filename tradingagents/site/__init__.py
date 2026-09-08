"""Public-site service helpers for TradingAgents.

The package intentionally avoids eager imports. Vercel imports
`tradingagents.site.api_app` for every public request; importing the expensive
TradingAgents graph at package import time can break lightweight public routes.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "AnalysisWorkerResult": ("tradingagents.site.analysis_worker", "AnalysisWorkerResult"),
    "build_latest_prices_payload": ("tradingagents.site.market_api", "build_latest_prices_payload"),
    "build_manual_portfolio_payload": ("tradingagents.site.portfolio_api", "build_manual_portfolio_payload"),
    "build_public_analysis_feed_payload": ("tradingagents.site.analysis_api", "build_public_analysis_feed_payload"),
    "build_public_analysis_outcomes_payload": ("tradingagents.site.analysis_api", "build_public_analysis_outcomes_payload"),
    "build_public_simulation_preview_payload": ("tradingagents.site.simulation_api", "build_public_simulation_preview_payload"),
    "build_public_stock_payload": ("tradingagents.site.public_api", "build_public_stock_payload"),
    "build_screener_payload": ("tradingagents.site.screener_api", "build_screener_payload"),
    "build_harness_runs_payload": ("tradingagents.site.harness_api", "build_harness_runs_payload"),
    "build_harness_run_payload": ("tradingagents.site.harness_api", "build_harness_run_payload"),
    "render_harness_page": ("tradingagents.site.harness_pages", "render_harness_page"),
    "build_forecast_payload": ("tradingagents.site.screener_api", "build_forecast_payload"),
    "build_ticker_search_payload": ("tradingagents.site.ticker_api", "build_ticker_search_payload"),
    "build_watchlist_payload": ("tradingagents.site.watchlist_api", "build_watchlist_payload"),
    "create_app": ("tradingagents.site.api_app", "create_app"),
    "process_queued_analysis_requests": ("tradingagents.site.analysis_worker", "process_queued_analysis_requests"),
    "queue_analysis_refresh_request": ("tradingagents.site.analysis_api", "queue_analysis_refresh_request"),
    "render_admin_console_page": ("tradingagents.site.web_pages", "render_admin_console_page"),
    "render_feature_detail_page": ("tradingagents.site.web_pages", "render_feature_detail_page"),
    "render_public_stock_page": ("tradingagents.site.web_pages", "render_public_stock_page"),
    "render_public_analysis_feed_page": ("tradingagents.site.web_pages", "render_public_analysis_feed_page"),
    "render_public_outcomes_page": ("tradingagents.site.web_pages", "render_public_outcomes_page"),
    "render_public_home_page": ("tradingagents.site.web_pages", "render_public_home_page"),
    "run_tradingagents_graph_for_request": ("tradingagents.site.analysis_runner", "run_tradingagents_graph_for_request"),
}
_SUBMODULES = {
    "analysis_api": "tradingagents.site.analysis_api",
    "analysis_runner": "tradingagents.site.analysis_runner",
    "analysis_worker": "tradingagents.site.analysis_worker",
    "api_app": "tradingagents.site.api_app",
    "auth": "tradingagents.site.auth",
    "harness_api": "tradingagents.site.harness_api",
    "harness_pages": "tradingagents.site.harness_pages",
    "market_api": "tradingagents.site.market_api",
    "outcome_worker": "tradingagents.site.outcome_worker",
    "paper_simulation_api": "tradingagents.site.paper_simulation_api",
    "paper_simulation_worker": "tradingagents.site.paper_simulation_worker",
    "portfolio_api": "tradingagents.site.portfolio_api",
    "public_api": "tradingagents.site.public_api",
    "screener_api": "tradingagents.site.screener_api",
    "seo": "tradingagents.site.seo",
    "simulation_api": "tradingagents.site.simulation_api",
    "ticker_api": "tradingagents.site.ticker_api",
    "watchlist_api": "tradingagents.site.watchlist_api",
    "web_pages": "tradingagents.site.web_pages",
}

__all__ = sorted([*_EXPORTS, *_SUBMODULES])


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        value = import_module(_SUBMODULES[name])
        globals()[name] = value
        return value
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

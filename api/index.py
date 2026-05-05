"""Vercel Python entrypoint for the TradingAgents API."""

from tradingagents.site.api_app import create_app


app = create_app()

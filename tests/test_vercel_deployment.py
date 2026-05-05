import importlib.util
import json
from pathlib import Path

from fastapi import FastAPI


ROOT = Path(__file__).resolve().parents[1]


def test_vercel_json_routes_api_and_health_to_fastapi_entrypoint():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))

    assert config["$schema"] == "https://openapi.vercel.sh/vercel.json"
    assert config["framework"] is None
    assert config["functions"]["api/index.py"]["maxDuration"] == 60
    assert {
        "source": "/",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/stocks",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/stocks/:path*",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/robots.txt",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/ads.txt",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/sitemap.xml",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/api/:path*",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/health",
        "destination": "/api/index.py",
    } in config["rewrites"]


def test_vercel_python_entrypoint_exposes_fastapi_app(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    spec = importlib.util.spec_from_file_location("vercel_api_index", ROOT / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert isinstance(module.app, FastAPI)
    assert module.app.title == "TradingAgents Korea API"


def test_site_package_import_stays_lightweight(monkeypatch):
    import sys

    for name in [
        "tradingagents.site",
        "tradingagents.site.analysis_runner",
        "tradingagents.graph",
        "tradingagents.graph.trading_graph",
    ]:
        sys.modules.pop(name, None)

    import tradingagents.site  # noqa: F401

    assert "tradingagents.site.analysis_runner" not in sys.modules
    assert "tradingagents.graph.trading_graph" not in sys.modules

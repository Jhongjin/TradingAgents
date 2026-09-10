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
    assert config["crons"] == [
        {
            "path": "/api/cron/process-paper-simulations",
            "schedule": "25 9 * * 1-5",
        },
        {
            "path": "/api/cron/process-analysis-outcomes",
            "schedule": "10 10 * * 1-5",
        },
        {
            "path": "/api/cron/run-harness",
            "schedule": "40 7 * * 1-5",
        },
        {
            "path": "/api/cron/process-harness-outcomes",
            "schedule": "20 10 * * 1-5",
        },
        {
            "path": "/api/cron/process-subscription-renewals",
            "schedule": "10 0 * * *",
        },
        {
            "path": "/api/cron/notify-harness-issue?slot=morning",
            "schedule": "56 22 * * 0-4",
        },
        {
            "path": "/api/cron/notify-harness-issue?slot=midday",
            "schedule": "25 1 * * 1-5",
        },
        {
            "path": "/api/cron/notify-exits",
            "schedule": "35 1 * * 1-5",
        },
        {
            "path": "/api/cron/notify-journal-targets",
            "schedule": "45 0 * * 1-5",
        },
        {
            "path": "/api/cron/notify-journal-targets",
            "schedule": "15 3 * * 1-5",
        },
        {
            "path": "/api/cron/notify-journal-targets",
            "schedule": "25 6 * * 1-5",
        },
        {
            "path": "/api/cron/notify-outcomes",
            "schedule": "40 10 * * 1-5",
        },
    ]
    assert {
        "source": "/harness",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/harness/:path*",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/analyses",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/analyses/:path*",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/outcomes",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/mypage",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/admin",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/privacy",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/terms",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/disclaimer",
        "destination": "/api/index.py",
    } in config["rewrites"]
    assert {
        "source": "/features/:path*",
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


def test_vercelignore_excludes_local_agent_and_test_artifacts():
    ignored = set((ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines())

    assert ".codex-test-venv" in ignored
    assert ".vercel" in ignored
    assert "tests" in ignored


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


def test_vercel_json_routes_pricing_page_to_fastapi_entrypoint():
    import json
    from pathlib import Path

    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert {"source": "/pricing", "destination": "/api/index.py"} in config["rewrites"]


def test_vercel_json_routes_billing_page_to_fastapi_entrypoint():
    import json
    from pathlib import Path

    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert {"source": "/billing", "destination": "/api/index.py"} in config["rewrites"]


def test_vercel_json_routes_admin_members_page_to_fastapi_entrypoint():
    import json
    from pathlib import Path

    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert {"source": "/admin/members", "destination": "/api/index.py"} in config["rewrites"]


def test_vercel_json_routes_llms_txt_to_fastapi_entrypoint():
    import json
    from pathlib import Path

    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert {"source": "/llms.txt", "destination": "/api/index.py"} in config["rewrites"]

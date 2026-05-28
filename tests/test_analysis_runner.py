from datetime import date
import os
import tempfile

import pytest

from tradingagents.site.analysis_runner import run_tradingagents_graph_for_request


class FakeGraph:
    instances = []

    def __init__(self, *, selected_analysts, debug, config):
        self.selected_analysts = selected_analysts
        self.debug = debug
        self.config = config
        self.last_analysis_run_id = "00000000-0000-0000-0000-000000000123"
        self.calls = []
        self.env = {}
        FakeGraph.instances.append(self)

    def propagate(self, ticker, trade_date):
        self.env = {
            "TRADINGAGENTS_RESULTS_DIR": os.getenv("TRADINGAGENTS_RESULTS_DIR"),
            "TRADINGAGENTS_CACHE_DIR": os.getenv("TRADINGAGENTS_CACHE_DIR"),
            "TRADINGAGENTS_MEMORY_LOG_PATH": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH"),
        }
        self.calls.append((ticker, trade_date))
        return {}, "Hold"


class MissingRunIdGraph(FakeGraph):
    def __init__(self, *, selected_analysts, debug, config):
        super().__init__(selected_analysts=selected_analysts, debug=debug, config=config)
        self.last_analysis_run_id = None


def test_tradingagents_runner_invokes_graph_and_returns_analysis_run_id(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_RESULTS_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_CACHE_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_MEMORY_LOG_PATH", raising=False)
    FakeGraph.instances = []
    request = {
        "ticker_code": "005930",
        "requested_trade_date": date(2026, 5, 5),
    }

    run_id = run_tradingagents_graph_for_request(
        request,
        config={"database_url": "sqlite+pysqlite:///:memory:"},
        selected_analysts=["market", "news"],
        graph_factory=FakeGraph,
    )

    graph = FakeGraph.instances[0]
    assert run_id == "00000000-0000-0000-0000-000000000123"
    assert graph.calls == [("005930", "2026-05-05")]
    assert graph.selected_analysts == ["market", "news"]
    assert graph.debug is False
    assert graph.config["storage_enabled"] is True
    assert graph.config["database_url"] == "sqlite+pysqlite:///:memory:"
    assert graph.config["results_dir"].startswith(os.path.join(tempfile.gettempdir(), "tradingagents", "worker"))
    assert graph.config["data_cache_dir"].startswith(os.path.join(tempfile.gettempdir(), "tradingagents", "worker"))
    assert graph.config["memory_log_path"].startswith(os.path.join(tempfile.gettempdir(), "tradingagents", "worker"))
    assert graph.env["TRADINGAGENTS_CACHE_DIR"] == graph.config["data_cache_dir"]
    assert graph.env["TRADINGAGENTS_RESULTS_DIR"] == graph.config["results_dir"]
    assert graph.env["TRADINGAGENTS_MEMORY_LOG_PATH"] == graph.config["memory_log_path"]
    assert os.getenv("TRADINGAGENTS_CACHE_DIR") is None


def test_tradingagents_runner_requires_persisted_analysis_run_id():
    request = {
        "ticker_code": "005930",
        "requested_trade_date": "2026-05-05",
    }

    with pytest.raises(RuntimeError, match="analysis_run_id"):
        run_tradingagents_graph_for_request(request, graph_factory=MissingRunIdGraph)


def test_tradingagents_runner_preserves_explicit_write_paths(tmp_path):
    FakeGraph.instances = []
    request = {
        "ticker_code": "005930",
        "requested_trade_date": "2026-05-05",
    }
    paths = {
        "results_dir": str(tmp_path / "logs"),
        "data_cache_dir": str(tmp_path / "cache"),
        "memory_log_path": str(tmp_path / "memory.md"),
    }

    run_tradingagents_graph_for_request(
        request,
        config={**paths, "database_url": "sqlite+pysqlite:///:memory:"},
        graph_factory=FakeGraph,
    )

    graph = FakeGraph.instances[0]
    assert graph.config["results_dir"] == paths["results_dir"]
    assert graph.config["data_cache_dir"] == paths["data_cache_dir"]
    assert graph.config["memory_log_path"] == paths["memory_log_path"]
    assert graph.env["TRADINGAGENTS_CACHE_DIR"] == paths["data_cache_dir"]

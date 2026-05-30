from datetime import date
from decimal import Decimal
import os
import tempfile

import pytest

from tradingagents.storage import (
    PaperSimulationAccountInput,
    PaperSimulationPositionInput,
    StorageRepository,
    create_storage_engine,
)
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
            "HOME": os.getenv("HOME"),
            "XDG_CACHE_HOME": os.getenv("XDG_CACHE_HOME"),
            "MPLCONFIGDIR": os.getenv("MPLCONFIGDIR"),
            "HF_HOME": os.getenv("HF_HOME"),
        }
        self.calls.append((ticker, trade_date))
        return {}, "Hold"


class MissingRunIdGraph(FakeGraph):
    def __init__(self, *, selected_analysts, debug, config):
        super().__init__(selected_analysts=selected_analysts, debug=debug, config=config)
        self.last_analysis_run_id = None


USER_ID = "00000000-0000-0000-0000-000000000001"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _record_closed_paper_position(repo: StorageRepository, *, ticker_code: str = "005930") -> None:
    account = repo.ensure_paper_simulation_account(PaperSimulationAccountInput(user_id=USER_ID))
    repo.record_paper_simulation_position(
        PaperSimulationPositionInput(
            account_id=account["id"],
            user_id=USER_ID,
            ticker_code=ticker_code,
            ticker_name="삼성전자" if ticker_code == "005930" else ticker_code,
            market="KOSPI",
            status="closed",
            quantity=1,
            entry_date=date(2026, 5, 5),
            entry_price=Decimal("70000"),
            exit_date=date(2026, 5, 7),
            exit_price=Decimal("76000"),
            realized_pnl=Decimal("6000"),
            realized_return=0.0857,
            decision_rating="Buy",
            decision_action="buy",
            metadata={"pattern_label": "20일선 위 / 단기 강세"},
        )
    )


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


def test_tradingagents_runner_adds_anonymous_paper_learning_context():
    repo = _repo()
    _record_closed_paper_position(repo)
    FakeGraph.instances = []

    run_tradingagents_graph_for_request(
        {
            "ticker_code": "005930",
            "requested_trade_date": date(2026, 5, 8),
            "user_id": USER_ID,
        },
        config={"database_url": "sqlite+pysqlite:///:memory:"},
        repo=repo,
        graph_factory=FakeGraph,
    )

    context = FakeGraph.instances[0].config["paper_learning_context"]
    assert "AI 모의투자 복기 참고자료" in context
    assert "비식별 집계" in context
    assert "실제 주문 아님" in context
    assert "20일선 위 / 단기 강세" in context
    assert USER_ID not in context


def test_tradingagents_runner_falls_back_to_marketwide_paper_learning_context():
    repo = _repo()
    _record_closed_paper_position(repo, ticker_code="005930")
    FakeGraph.instances = []

    run_tradingagents_graph_for_request(
        {"ticker_code": "000660", "requested_trade_date": date(2026, 5, 8)},
        config={"database_url": "sqlite+pysqlite:///:memory:"},
        repo=repo,
        graph_factory=FakeGraph,
    )

    context = FakeGraph.instances[0].config["paper_learning_context"]
    assert "전체 종목의 모의 청산 1건" in context
    assert "20일선 위 / 단기 강세" in context


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


def test_tradingagents_runner_routes_serverless_write_paths_to_tmp(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("HOME", "/home/sbx_user1051")
    monkeypatch.setenv("TRADINGAGENTS_RESULTS_DIR", "/home/sbx_user1051/.tradingagents/logs")
    monkeypatch.setenv("TRADINGAGENTS_CACHE_DIR", "/home/sbx_user1051/.tradingagents/cache")
    monkeypatch.setenv("TRADINGAGENTS_MEMORY_LOG_PATH", "/home/sbx_user1051/.tradingagents/memory/trading_memory.md")
    FakeGraph.instances = []
    request = {
        "ticker_code": "005930",
        "requested_trade_date": "2026-05-05",
    }

    run_tradingagents_graph_for_request(
        request,
        config={"database_url": "sqlite+pysqlite:///:memory:"},
        graph_factory=FakeGraph,
    )

    worker_root = os.path.join(tempfile.gettempdir(), "tradingagents", "worker")
    graph = FakeGraph.instances[0]
    assert graph.config["results_dir"] == os.path.join(worker_root, "logs")
    assert graph.config["data_cache_dir"] == os.path.join(worker_root, "cache")
    assert graph.config["memory_log_path"] == os.path.join(worker_root, "memory", "trading_memory.md")
    assert graph.env["TRADINGAGENTS_CACHE_DIR"] == graph.config["data_cache_dir"]
    assert graph.env["TRADINGAGENTS_RESULTS_DIR"] == graph.config["results_dir"]
    assert graph.env["TRADINGAGENTS_MEMORY_LOG_PATH"] == graph.config["memory_log_path"]
    assert graph.env["HOME"] == os.path.join(worker_root, "home")
    assert graph.env["XDG_CACHE_HOME"] == os.path.join(worker_root, "xdg-cache")
    assert graph.env["MPLCONFIGDIR"] == os.path.join(worker_root, "matplotlib")
    assert graph.env["HF_HOME"] == os.path.join(worker_root, "hf")
    assert os.getenv("HOME") == "/home/sbx_user1051"

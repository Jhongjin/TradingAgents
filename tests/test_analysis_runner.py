from datetime import date

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
        FakeGraph.instances.append(self)

    def propagate(self, ticker, trade_date):
        self.calls.append((ticker, trade_date))
        return {}, "Hold"


class MissingRunIdGraph(FakeGraph):
    def __init__(self, *, selected_analysts, debug, config):
        super().__init__(selected_analysts=selected_analysts, debug=debug, config=config)
        self.last_analysis_run_id = None


def test_tradingagents_runner_invokes_graph_and_returns_analysis_run_id():
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


def test_tradingagents_runner_requires_persisted_analysis_run_id():
    request = {
        "ticker_code": "005930",
        "requested_trade_date": "2026-05-05",
    }

    with pytest.raises(RuntimeError, match="analysis_run_id"):
        run_tradingagents_graph_for_request(request, graph_factory=MissingRunIdGraph)

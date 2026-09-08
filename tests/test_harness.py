import json

import pytest

from tradingagents.execution import AuditLedger, KoreaTradingRules, PaperBroker, PaperBrokerAdapter, RiskLimits, TradingMandate
from tradingagents.harness import (
    PLAYBOOK,
    PipelineConfig,
    get_prompt,
    list_prompts,
    render_prompt,
    run_daily_pipeline,
    run_playbook,
    run_task,
)
from tradingagents.harness.pipeline import Confirmation, graph_confirmer, playbook_confirmer
from tradingagents.harness.tasks import HarnessTask, parse_json_output
from tradingagents.screener import MarketSnapshot, MarketSnapshotRow, ScreenerConfig, screen_korean_market


# ---------------------------------------------------------------- playbook
def test_playbook_has_core_ten_plus_extended_prompts_with_schemas():
    core = list_prompts(extended=False)
    assert len(core) == 10
    assert [prompt.order for prompt in core] == list(range(1, 11))
    assert core[0].id == "market_analysis"
    assert core[-1].id == "global_events"
    prompts = list_prompts()
    assert len(prompts) == 17
    assert [prompt.order for prompt in prompts] == list(range(1, 18))
    assert {prompt.id for prompt in prompts[10:]} == {
        "investor_flows",
        "disclosure_events",
        "scenario_catalysts",
        "devils_advocate",
        "execution_plan",
        "post_trade_review",
        "market_regime",
    }
    for prompt in PLAYBOOK:
        assert "summary" in prompt.schema
        assert "evidence" in prompt.schema
        for placeholder in prompt.placeholders:
            assert f"[{placeholder}]" in prompt.template


def test_render_prompt_fills_placeholders_via_aliases():
    text = render_prompt("technical_analysis", {"ticker": "삼성전자(005930)"})
    assert "[주식]" not in text
    assert "삼성전자(005930)" in text
    text = render_prompt("market_analysis", {"sector": "반도체"})
    assert "반도체에 중점" in text
    with pytest.raises(ValueError):
        render_prompt("market_analysis", {})
    with pytest.raises(KeyError):
        get_prompt("nope")
    assert render_prompt("growth_vs_dividend", {}) == get_prompt("growth_vs_dividend").template


def test_parse_json_output_tolerates_fences_and_prose():
    assert parse_json_output('```json\n{"a": 1}\n```')[0] == {"a": 1}
    assert parse_json_output('결과입니다: {"a": {"b": 2}} 끝')[0] == {"a": {"b": 2}}
    assert parse_json_output("")[1] == "empty response"
    assert "invalid JSON" in parse_json_output("{oops")[1]
    assert parse_json_output("[1,2]")[1] == "JSON root must be an object"


def test_run_task_and_playbook_with_stub_llm():
    seen = []

    def llm(prompt):
        seen.append(prompt)
        return json.dumps({"summary": "요약", "confidence": 0.7, "evidence": [], "caveats": []}, ensure_ascii=False)

    results = run_playbook(llm, values={"target": "삼성전자"}, context={"chart": [{"close": 1}], "forecast": {"x": 1}}, extended=False)
    assert [result.status for result in results] == ["ok"] * 10
    assert results[0].data["summary"] == "요약"
    assert "## 제공 데이터" in seen[0]
    assert "previous_conclusions" in seen[1]
    assert "chart" not in seen[4]  # economic_indicators declares no chart context
    payload = results[0].as_dict()
    assert payload["task_id"] == "market_analysis"

    full = run_playbook(llm, values={"target": "삼성전자"})
    assert len(full) == 17
    assert full[-1].task_id == "market_regime"

    subset = run_playbook(llm, values={"target": "x"}, prompt_ids=["risk_management", "market_analysis"])
    assert [result.task_id for result in subset] == ["market_analysis", "risk_management"]


def test_run_task_reports_llm_and_parse_errors():
    task = HarnessTask(prompt=get_prompt("market_sentiment"), values={"target": "x"})

    def broken(prompt):
        raise RuntimeError("boom")

    result = run_task(task, broken)
    assert result.status == "llm_error"
    assert "boom" in result.error
    result = run_task(task, lambda prompt: "not json")
    assert result.status == "parse_error"


# ---------------------------------------------------------------- pipeline
def _points(count=200, drift=0.004):
    rows = []
    close = 50_000.0
    for index in range(count):
        close *= 1 + drift
        rows.append({"date": f"d{index}", "close": round(close, 2), "volume": 1_000_000})
    return rows


def _screener_result(points, codes=("005930", "000660")):
    snapshot = MarketSnapshot(
        as_of_date="2026-09-05",
        markets=("KOSPI",),
        rows=[
            MarketSnapshotRow(code, code, "KOSPI", 70_000.0, 1e7, 5e11, 4e14, 0.5, 12.0, 1.2, 2.0)
            for code in codes
        ],
    )
    return screen_korean_market(snapshot=snapshot, history_fetcher=lambda code, s, e: points, config=ScreenerConfig(top_n=5, min_composite=-10))


def test_pipeline_fails_closed_without_confirmer():
    points = _points()
    result = run_daily_pipeline(
        "2026-09-05",
        config=PipelineConfig(min_probability_up=0, min_expected_return=-1),
        screener_runner=lambda when, cfg: _screener_result(points),
        history_fetcher=lambda code, s, e: points,
        current_prices={"005930": 70_000, "000660": 70_000},
    )
    assert result.dry_run
    assert all(decision.stage == "confirmation_rejected" for decision in result.decisions)
    assert any("fail closed" in note for note in result.notes)
    assert result.orders == []
    assert result.as_dict()["execution_boundary"] == "dry_run_no_orders"


def test_pipeline_deterministic_mode_dry_run_places_no_fills():
    points = _points()
    result = run_daily_pipeline(
        "2026-09-05",
        config=PipelineConfig(require_llm_confirmation=False, min_probability_up=0, min_expected_return=-1),
        screener_runner=lambda when, cfg: _screener_result(points),
        history_fetcher=lambda code, s, e: points,
        current_prices={"005930": 70_000, "000660": 70_000},
    )
    assert [decision.stage for decision in result.decisions] == ["ordered", "ordered"]
    assert all(decision.order["status"] == "dry_run" for decision in result.decisions)
    assert result.account_after["cash"] == 10_000_000


def test_pipeline_with_confirmer_sizes_gates_and_fills(tmp_path):
    points = _points()
    ledger = AuditLedger(tmp_path / "audit.jsonl")

    def confirmer(candidate, context):
        assert "forecast" in context and "risk_metrics" in context
        rating = "Buy" if candidate.code == "005930" else "Hold"
        return Confirmation(rating=rating, confidence=0.9, stop_loss_pct=0.04, take_profit_pct=0.12, source="test")

    result = run_daily_pipeline(
        "2026-09-05",
        config=PipelineConfig(dry_run=False, min_probability_up=0, min_expected_return=-1, mandate=TradingMandate(max_positions=5)),
        screener_runner=lambda when, cfg: _screener_result(points),
        history_fetcher=lambda code, s, e: points,
        confirmer=confirmer,
        ledger=ledger,
        current_prices={"005930": 70_000, "000660": 70_000},
    )
    by_code = {decision.code: decision for decision in result.decisions}
    assert by_code["005930"].stage == "ordered"
    assert by_code["005930"].order["status"] == "filled"
    assert by_code["005930"].sizing["stop_price"] == pytest.approx(70_000 * 0.96)
    assert by_code["005930"].mandate["approved"]
    assert by_code["000660"].stage == "confirmation_rejected"
    assert result.account_after["cash"] < 10_000_000
    assert result.audit_sequence_start == 1
    assert result.audit_sequence_end == ledger.sequence
    assert ledger.verify_chain() == (True, None)
    events = [record.event_type for record in ledger.iter_records()]
    assert events[0] == "screen"
    assert "order" in events and events[-1] == "cycle_complete"


def test_pipeline_rejects_on_forecast_gate_and_confirmer_error():
    points = _points(drift=-0.004)

    def exploding(candidate, context):
        raise RuntimeError("llm down")

    result = run_daily_pipeline(
        "2026-09-05",
        config=PipelineConfig(min_probability_up=0.55, min_expected_return=0.0),
        screener_runner=lambda when, cfg: _screener_result(points),
        history_fetcher=lambda code, s, e: points,
        confirmer=exploding,
        current_prices={"005930": 70_000, "000660": 70_000},
    )
    assert all(decision.stage == "forecast_rejected" for decision in result.decisions)

    up = _points()
    result = run_daily_pipeline(
        "2026-09-05",
        config=PipelineConfig(min_probability_up=0, min_expected_return=-1),
        screener_runner=lambda when, cfg: _screener_result(up),
        history_fetcher=lambda code, s, e: up,
        confirmer=exploding,
    )
    assert all(decision.stage == "confirmation_rejected" for decision in result.decisions)
    assert all("fail closed" in decision.reasons[0] for decision in result.decisions)


def test_pipeline_exits_positions_on_stop_and_take_profit():
    points = _points()
    broker = PaperBrokerAdapter(
        PaperBroker.with_limits(initial_cash=10_000_000, limits=RiskLimits(max_position_weight=0.5), currency="KRW", execution_rules=KoreaTradingRules())
    )
    from tradingagents.execution import OrderIntent, OrderSide

    broker.broker.submit_order(OrderIntent("111111", OrderSide.BUY, 10), 100_000)
    broker.broker.submit_order(OrderIntent("222222", OrderSide.BUY, 10), 100_000)
    result = run_daily_pipeline(
        "2026-09-05",
        config=PipelineConfig(dry_run=False, stop_loss_pct=0.05, take_profit_pct=0.10),
        screener_runner=lambda when, cfg: _screener_result(points, codes=()),
        history_fetcher=lambda code, s, e: points,
        broker=broker,
        current_prices={"111111": 90_000, "222222": 112_000},
    )
    exits = {decision.code: decision for decision in result.decisions if decision.stage == "exit"}
    assert exits["111111"].reasons[0] == "stop_loss"
    assert exits["222222"].reasons[0] == "take_profit"
    assert broker.account_snapshot({}).positions == {}


def test_playbook_confirmer_maps_structured_outputs():
    outputs = {
        "technical_analysis": {"summary": "상승", "action": "Buy", "confidence": 0.8, "technical_score": 0.7},
        "risk_management": {"summary": "보통", "stop_loss_pct": 5, "take_profit_pct": 0.12, "risk_score": 0.3},
    }

    def llm(prompt):
        for key, value in outputs.items():
            if get_prompt(key).title in prompt:
                return json.dumps(value, ensure_ascii=False)
        raise AssertionError(prompt)

    candidate = _screener_result(_points()).candidates[0]
    confirmation = playbook_confirmer(llm)(candidate, {"chart": [], "forecast": {}, "risk_metrics": {}, "candidate": candidate.as_dict()})
    assert confirmation.rating == "Buy"
    assert confirmation.confidence == 0.8
    assert confirmation.stop_loss_pct == 0.05
    assert confirmation.take_profit_pct == 0.12
    assert confirmation.source == "playbook"

    outputs["risk_management"]["risk_score"] = 0.9
    confirmation = playbook_confirmer(llm)(candidate, {"candidate": candidate.as_dict()})
    assert confirmation.rating == "Hold"


def test_graph_confirmer_uses_trading_graph_rating():
    class FakeGraph:
        last_analysis_run_id = "run-1"

        def propagate(self, ticker, trade_date):
            return {"final_trade_decision": "**Rating**: Overweight\nthesis"}, "Overweight"

    candidate = _screener_result(_points()).candidates[0]
    confirmation = graph_confirmer(lambda: FakeGraph(), trade_date="2026-09-05")(candidate, {})
    assert confirmation.rating == "Overweight"
    assert confirmation.is_bullish
    assert confirmation.raw["analysis_run_id"] == "run-1"


def test_graph_confirmer_injects_harness_context_when_factory_accepts_it():
    captured = {}

    class FakeGraph:
        last_analysis_run_id = None

        def propagate(self, ticker, trade_date):
            return {"final_trade_decision": "**Rating**: Buy"}, "Buy"

    def factory(harness_context: str = ""):
        captured["context"] = harness_context
        return FakeGraph()

    candidate = _screener_result(_points()).candidates[0]
    context = {"candidate": candidate.as_dict(), "forecast": {"backend": "naive", "horizon": 20, "expected_return": 0.03, "probability_up": 0.6}, "risk_metrics": {"annualized_volatility": 0.3}}
    confirmation = graph_confirmer(factory, trade_date="2026-09-05")(candidate, context)
    assert confirmation.rating == "Buy"
    assert "[하네스 증거 요약]" in captured["context"]
    assert "스크리너 순위 1" in captured["context"]
    assert "통계 예측(naive)" in captured["context"]


def test_pipeline_persists_run_and_decisions_when_repo_given(tmp_path):
    from tradingagents.storage import StorageRepository, create_storage_engine

    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    points = _points()
    result = run_daily_pipeline(
        "2026-09-05",
        config=PipelineConfig(require_llm_confirmation=False, min_probability_up=0, min_expected_return=-1),
        screener_runner=lambda when, cfg: _screener_result(points),
        history_fetcher=lambda code, s, e: points,
        current_prices={"005930": 70_000, "000660": 70_000},
        repo=repo,
        confirmer_name="none",
    )
    assert result.run_id
    stored = repo.get_harness_run(result.run_id)
    assert stored["as_of_date"].isoformat() == "2026-09-05"
    assert stored["dry_run"] is True
    assert stored["confirmer"] == "none"
    assert stored["candidate_count"] == 2
    assert stored["order_count"] == 2
    assert len(stored["decisions"]) == 2
    first = stored["decisions"][0]
    assert first["stage"] == "ordered"
    assert first["order_status"] == "dry_run"
    assert first["quantity"] > 0
    assert first["detail_json"]["sizing"]["quantity"] == first["quantity"]
    assert repo.latest_harness_run()["id"] == result.run_id
    assert repo.list_harness_decisions(ticker_code="005930")[0]["harness_run_id"] == result.run_id
    assert result.as_dict()["run_id"] == result.run_id


def test_pipeline_config_validation():
    with pytest.raises(ValueError):
        PipelineConfig(confirm_top_n=0)
    with pytest.raises(ValueError):
        PipelineConfig(stop_loss_pct=1.5)

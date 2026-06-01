from datetime import date, timedelta
from types import SimpleNamespace

from tradingagents.storage import (
    AnalysisRunInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)
from tradingagents.site.paper_simulation_api import (
    build_member_paper_simulation_payload,
    build_paper_learning_context_payload,
)
from tradingagents.site.paper_simulation_worker import process_paper_simulation_candidates, process_paper_simulations


USER_ID = "00000000-0000-0000-0000-000000000001"


class _Point:
    def __init__(self, day: str, close: float, *, volume: int = 1000):
        self.day = day
        self.close = close
        self.volume = volume

    def as_dict(self):
        return {
            "date": self.day,
            "open": self.close,
            "high": self.close,
            "low": self.close,
            "close": self.close,
            "volume": self.volume,
        }


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def test_paper_simulation_worker_persists_member_position(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            user_id=USER_ID,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Buy",
            action="buy",
        )
    )
    repo.complete_analysis_run(run_id)
    monkeypatch.setattr(
        "tradingagents.site.paper_simulation_worker.get_ohlcv_chart_series",
        lambda *args, **kwargs: SimpleNamespace(
            vendor="fixture",
            points=[
                _Point("2026-05-05", 70_000),
                _Point("2026-05-06", 73_000),
                _Point("2026-05-07", 76_000),
            ],
        ),
    )

    results = process_paper_simulation_candidates(repo, limit=5, as_of_date="2026-05-07")
    payload = build_member_paper_simulation_payload(repo, user_id=USER_ID)

    assert len(results) == 1
    assert results[0].status == "created"
    assert results[0].simulation_status == "closed"
    assert results[0].position_id is not None
    assert repo.list_paper_simulation_candidates() == []
    assert payload["status"] == "available"
    assert payload["execution_boundary"] == "simulation_only_no_orders"
    assert payload["execution_boundary_label"] == "실제 주문 없음 · 가상매매 전용"
    assert payload["summary"]["closed_count"] == 1
    assert payload["summary"]["win_count"] == 1
    assert payload["summary"]["learning"]["best_bucket"]["label"] == "Buy / buy"
    assert payload["summary"]["learning"]["best_bucket"]["win_rate"] == 1
    assert payload["positions"][0]["analysis_run_id"] == run_id
    assert payload["positions"][0]["ticker_code"] == "005930"
    assert payload["positions"][0]["metadata"]["entry_reason"]["execution_boundary"] == "simulation_only_no_orders"
    assert "가상 진입" in payload["positions"][0]["metadata"]["entry_reason"]["summary"]
    assert payload["positions"][0]["metadata"]["exit_reason_detail"]["reason"] == "take_profit"
    assert payload["positions"][0]["metadata"]["exit_reason_detail"]["label"] == "익절 기준 도달"
    assert payload["positions"][0]["metadata"]["post_trade_evaluation"]["outcome_label"] == "목표 달성"
    assert "실현 수익률" in payload["positions"][0]["metadata"]["post_trade_evaluation"]["summary"]
    assert payload["events"][0]["event_type"] == "exit"
    assert payload["events"][0]["metadata"]["reason_label"] == "익절 기준 도달"
    assert payload["events"][0]["metadata"]["outcome_label"] == "목표 달성"


def test_paper_simulation_worker_groups_learning_by_entry_pattern(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            user_id=USER_ID,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Buy",
            action="buy",
        )
    )
    repo.complete_analysis_run(run_id)
    start = date(2026, 4, 11)
    history = [
        _Point((start + timedelta(days=index)).isoformat(), 50_000 + (index * 1_000))
        for index in range(25)
    ]
    history[-1] = _Point("2026-05-05", 74_000, volume=3_000)
    points = history + [
        _Point("2026-05-06", 81_000),
        _Point("2026-05-07", 82_000),
    ]
    monkeypatch.setattr(
        "tradingagents.site.paper_simulation_worker.get_ohlcv_chart_series",
        lambda *args, **kwargs: SimpleNamespace(vendor="fixture", points=points),
    )

    results = process_paper_simulation_candidates(repo, limit=5, as_of_date="2026-05-07")
    payload = build_member_paper_simulation_payload(repo, user_id=USER_ID)
    metadata = payload["positions"][0]["metadata"]

    assert results[0].status == "created"
    assert metadata["entry_pattern"]["status"] == "available"
    assert metadata["pattern_label"] == "20일선 위 / 단기 강세 / 거래량 증가"
    assert payload["summary"]["learning"]["best_bucket"]["label"] == metadata["pattern_label"]

    context = build_paper_learning_context_payload(repo, ticker_code="005930")
    assert context["status"] == "available"
    assert context["sample_count"] == 1
    assert "비식별 집계" in context["context_text"]
    assert "실제 주문 아님" in context["context_text"]
    assert "20일선 위 / 단기 강세 / 거래량 증가" in context["context_text"]


def test_paper_simulation_worker_refreshes_open_positions_until_virtual_exit(monkeypatch):
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            user_id=USER_ID,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=run_id,
            rating="Buy",
            action="buy",
        )
    )
    repo.complete_analysis_run(run_id)

    def fake_chart(*args, **kwargs):
        end_date = kwargs.get("end_date") or args[2]
        points = [
            _Point("2026-05-05", 70_000),
            _Point("2026-05-06", 71_000),
        ]
        if str(end_date) >= "2026-05-07":
            points.append(_Point("2026-05-07", 76_000))
        return SimpleNamespace(vendor="fixture", points=points)

    monkeypatch.setattr("tradingagents.site.paper_simulation_worker.get_ohlcv_chart_series", fake_chart)

    created = process_paper_simulations(repo, limit=5, as_of_date="2026-05-06")
    open_payload = build_member_paper_simulation_payload(repo, user_id=USER_ID)
    refreshed = process_paper_simulations(repo, limit=5, as_of_date="2026-05-07")
    closed_payload = build_member_paper_simulation_payload(repo, user_id=USER_ID)

    assert len(created) == 1
    assert created[0].status == "created"
    assert created[0].simulation_status == "open"
    assert created[0].unrealized_return is not None
    assert open_payload["summary"]["open_count"] == 1
    assert open_payload["summary"]["average_unrealized_return"] is not None
    assert refreshed[0].status == "closed"
    assert refreshed[0].simulation_status == "closed"
    assert closed_payload["summary"]["open_count"] == 0
    assert closed_payload["summary"]["closed_count"] == 1
    assert closed_payload["positions"][0]["status"] == "closed"
    assert closed_payload["positions"][0]["metadata"]["exit_reason_detail"]["reason"] == "take_profit"
    assert closed_payload["positions"][0]["metadata"]["post_trade_evaluation"]["outcome_label"] == "목표 달성"
    assert closed_payload["events"][0]["event_type"] == "exit"
    assert closed_payload["events"][0]["metadata"]["evaluation_summary"].startswith("목표 달성")
    assert len(closed_payload["events"]) == 2

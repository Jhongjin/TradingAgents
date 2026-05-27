from datetime import date
from types import SimpleNamespace

from tradingagents.storage import AnalysisRunInput, TradeDecisionInput, StorageRepository, create_storage_engine
from tradingagents.site.paper_simulation_api import build_member_paper_simulation_payload
from tradingagents.site.paper_simulation_worker import process_paper_simulation_candidates


USER_ID = "00000000-0000-0000-0000-000000000001"


class _Point:
    def __init__(self, day: str, close: float):
        self.day = day
        self.close = close

    def as_dict(self):
        return {
            "date": self.day,
            "open": self.close,
            "high": self.close,
            "low": self.close,
            "close": self.close,
            "volume": 1000,
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
    assert payload["summary"]["closed_count"] == 1
    assert payload["summary"]["win_count"] == 1
    assert payload["positions"][0]["analysis_run_id"] == run_id
    assert payload["positions"][0]["ticker_code"] == "005930"
    assert payload["events"][0]["event_type"] == "exit"

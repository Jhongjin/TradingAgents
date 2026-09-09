from datetime import date

import pytest

from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, create_storage_engine


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def test_latest_harness_entry_dates_ignores_dry_runs_and_keeps_newest():
    repo = _repo()
    real = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 8), broker="kis", dry_run=False, confirmer="debate", candidate_count=1, order_count=1))
    dry = repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 9), broker="paper", dry_run=True, confirmer="none", candidate_count=1, order_count=1))
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=real, as_of_date=date(2026, 9, 8), ticker_code="000660", stage="ordered", ticker_name="SK하이닉스", market="KOSPI", order_status="accepted", quantity=3))
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=real, as_of_date=date(2026, 9, 1), ticker_code="000660", stage="ordered", ticker_name="SK하이닉스", market="KOSPI", order_status="filled", quantity=1))
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=real, as_of_date=date(2026, 9, 8), ticker_code="005380", stage="ordered", ticker_name="현대차", market="KOSPI", order_status="rejected", quantity=1))
    repo.add_harness_decision(HarnessDecisionInput(harness_run_id=dry, as_of_date=date(2026, 9, 9), ticker_code="005930", stage="ordered", ticker_name="삼성전자", market="KOSPI", order_status="dry_run", quantity=5))

    assert repo.latest_harness_entry_dates() == {"000660": date(2026, 9, 8)}
    with pytest.raises(ValueError):
        repo.latest_harness_entry_dates(limit=0)

from datetime import date, datetime, timezone

import pytest

from tradingagents.site import (
    build_public_analysis_feed_payload,
    build_public_analysis_outcomes_payload,
    queue_analysis_refresh_request,
)
from tradingagents.site.analysis_api import AnalysisRequestQuotaExceeded, build_member_analysis_requests_payload
from tradingagents.storage import (
    AgentReportInput,
    AnalysisOutcomeInput,
    AnalysisRequestInput,
    AnalysisRunInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)


USER_ID = "00000000-0000-0000-0000-000000000001"


class NoBundleFeedRepository(StorageRepository):
    def get_analysis_bundle(self, analysis_run_id: str):
        raise AssertionError("public feed should not load full analysis bundles")


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def test_queue_analysis_refresh_request_persists_queued_request():
    repo = _repo()

    payload = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        reason="stale",
    )
    queued = repo.list_analysis_requests(user_id=USER_ID)

    assert payload["status"] == "queued"
    assert payload["duplicate"] is False
    assert payload["ticker"]["code"] == "005930"
    assert payload["public_stock_path"] == "/stocks/005930"
    assert payload["status_label"] == "대기"
    assert payload["requested_trade_date"] == "2026-05-05"
    assert queued[0]["id"] == payload["request_id"]
    assert queued[0]["requested_trade_date"] == date(2026, 5, 5)


def test_queue_analysis_refresh_request_reuses_existing_active_request():
    repo = _repo()

    first = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        reason="stale",
    )
    second = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        reason="button retry",
    )
    queued = repo.list_analysis_requests(user_id=USER_ID)

    assert first["status"] == "queued"
    assert second["status"] == "already_queued"
    assert second["duplicate"] is True
    assert second["public_stock_path"] == "/stocks/005930"
    assert second["status_label"] == "대기"
    assert second["request_id"] == first["request_id"]
    assert len(queued) == 1


def test_queue_analysis_refresh_request_allows_duplicate_retry_over_quota():
    repo = _repo()

    first = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        active_limit=1,
        daily_limit=1,
    )
    second = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        active_limit=1,
        daily_limit=1,
    )

    assert first["status"] == "queued"
    assert first["quota"]["active_used"] == 1
    assert first["quota"]["daily_used"] == 1
    assert second["status"] == "already_queued"
    assert second["request_id"] == first["request_id"]


def test_queue_analysis_refresh_request_enforces_active_quota():
    repo = _repo()

    queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        active_limit=1,
        daily_limit=20,
    )

    with pytest.raises(AnalysisRequestQuotaExceeded) as exc_info:
        queue_analysis_refresh_request(
            repo,
            ticker="000660",
            user_id=USER_ID,
            requested_trade_date="2026-05-05",
            active_limit=1,
            daily_limit=20,
        )

    payload = exc_info.value.to_payload()
    assert payload["status"] == "quota_exceeded"
    assert payload["kind"] == "active"
    assert payload["limit"] == 1
    assert repo.count_analysis_requests(user_id=USER_ID) == 1


def test_queue_analysis_refresh_request_enforces_daily_quota():
    repo = _repo()
    now = datetime.now(timezone.utc)

    queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        active_limit=20,
        daily_limit=1,
        now=now,
    )

    with pytest.raises(AnalysisRequestQuotaExceeded) as exc_info:
        queue_analysis_refresh_request(
            repo,
            ticker="000660",
            user_id=USER_ID,
            requested_trade_date="2026-05-05",
            active_limit=20,
            daily_limit=1,
            now=now,
        )

    payload = exc_info.value.to_payload()
    assert payload["kind"] == "daily"
    assert payload["window_hours"] == 24
    assert payload["used"] == 1


def test_queue_analysis_refresh_request_rejects_non_korean_ticker():
    repo = _repo()

    with pytest.raises(ValueError, match="Korean 6-digit"):
        queue_analysis_refresh_request(repo, ticker="AAPL", user_id=USER_ID)


def test_build_member_analysis_requests_payload_surfaces_queue_transparency(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_REQUEST_ACTIVE_LIMIT", "2")
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_REQUEST_DAILY_LIMIT", "10")
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    completed_request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            ticker_name="삼성전자",
            requested_trade_date=date(2026, 5, 5),
            reason="done",
        )
    )
    repo.update_analysis_request_status(completed_request_id, status="completed", analysis_run_id=run_id)
    queued_request_id = repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="000660",
            ticker_name="SK하이닉스",
            requested_trade_date=date(2026, 5, 6),
            reason="refresh",
        )
    )

    payload = build_member_analysis_requests_payload(repo, user_id=USER_ID)
    rows = {row["id"]: row for row in payload["items"]}

    assert payload["summary"]["quota_policy"]["active_limit"] == 2
    assert payload["summary"]["quota_policy"]["active_used"] == 1
    assert payload["summary"]["quota_policy"]["daily_used"] == 2
    assert payload["summary"]["queued_count"] == 1
    assert rows[completed_request_id]["report_path"] == f"/analyses/{run_id}"
    assert rows[completed_request_id]["next_action_label"] == "리포트 보기"
    assert rows[queued_request_id]["member_queue_position"] == 1
    assert rows[queued_request_id]["queue_scope_label"] == "내 활성 요청 기준"
    assert "운영 worker" in rows[queued_request_id]["status_hint"]


def test_public_analysis_feed_lists_completed_public_runs_only():
    repo = _repo()
    public_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    private_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 6),
            visibility="private",
        )
    )
    pending_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 7),
            visibility="public",
        )
    )
    repo.add_agent_report(
        AgentReportInput(
            analysis_run_id=public_run_id,
            role="market",
            content="market report",
        )
    )
    repo.record_trade_decision(
        TradeDecisionInput(
            analysis_run_id=public_run_id,
            rating="Hold",
            action="hold",
            raw_decision="Rating: Hold",
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=public_run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
            status="completed",
        )
    )
    repo.complete_analysis_run(public_run_id)
    repo.complete_analysis_run(private_run_id)

    payload = build_public_analysis_feed_payload(repo, ticker="005930.KS")

    assert payload["ticker_code"] == "005930"
    assert [item["id"] for item in payload["items"]] == [public_run_id]
    assert payload["summary"]["completed_count"] == 1
    assert payload["summary"]["unique_ticker_count"] == 1
    assert payload["summary"]["market_counts"] == {"KOSPI": 1}
    assert payload["summary"]["latest_trade_date"] == "2026-05-05"
    assert payload["items"][0]["report_count"] == 1
    assert payload["items"][0]["decision_rating"] == "Hold"
    assert payload["items"][0]["completed_outcome_count"] == 1
    assert payload["items"][0]["alpha_return"] == 0.03
    assert payload["summary"]["outcome_covered_count"] == 1
    assert payload["summary"]["outcome_coverage_rate"] == 1.0
    assert payload["summary"]["average_alpha_return"] == 0.03
    assert private_run_id not in [item["id"] for item in payload["items"]]
    assert pending_run_id not in [item["id"] for item in payload["items"]]


def test_public_analysis_feed_validates_limit():
    repo = _repo()

    with pytest.raises(ValueError, match="cannot exceed 1"):
        build_public_analysis_feed_payload(repo, limit=2, max_limit=1)


def test_public_analysis_feed_uses_compact_feed_query_not_bundle_lookup():
    repo = NoBundleFeedRepository(create_storage_engine())
    repo.create_schema()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    repo.complete_analysis_run(run_id)

    payload = build_public_analysis_feed_payload(repo)

    assert payload["status"] == "available"
    assert [item["id"] for item in payload["items"]] == [run_id]


def test_public_analysis_outcomes_payload_summarizes_completed_alpha():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    private_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 6),
            visibility="private",
        )
    )
    repo.complete_analysis_run(run_id)
    repo.complete_analysis_run(private_run_id)
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
            status="completed",
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=private_run_id,
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 6),
            evaluated_at=date(2026, 5, 13),
            horizon_days=5,
            raw_return=-0.10,
            benchmark_return=0.01,
            alpha_return=-0.11,
            status="completed",
        )
    )

    payload = build_public_analysis_outcomes_payload(repo, ticker="005930")

    assert payload["ticker_code"] == "005930"
    assert payload["item_count"] == 1
    assert payload["items"][0]["analysis_run_id"] == run_id
    assert payload["summary"]["completed_count"] == 1
    assert payload["summary"]["positive_alpha_count"] == 1
    assert payload["summary"]["average_alpha_return"] == 0.03


def test_public_analysis_outcomes_payload_degrades_on_storage_failure():
    class BrokenRepo:
        def list_analysis_outcomes(self, *args, **kwargs):
            raise RuntimeError("secret database detail")

    payload = build_public_analysis_outcomes_payload(BrokenRepo(), ticker="005930")

    assert payload["status"] == "unavailable"
    assert payload["ticker_code"] == "005930"
    assert payload["item_count"] == 0
    assert payload["error"] == "RuntimeError"
    assert "secret" not in str(payload)

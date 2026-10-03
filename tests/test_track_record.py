"""The account's own closed trades reach the next decision, and only the past ones."""

import json

from tradingagents.execution import TradingMandate
from tradingagents.harness.pipeline import Confirmation, PipelineConfig, run_daily_pipeline
from tradingagents.harness.track_record import (
    build_track_record,
    latest_run_id,
    review_track_record,
    summarize_closed,
    track_record_text,
)
from tests.test_harness import _points, _screener_result
from tests.test_paper_account import _repo, _seed_account


def _closed(code, exit_date, ret, reason="stop_loss", confidence=0.7):
    return {"ticker_code": code, "ticker_name": code, "entry_date": "2026-09-01", "exit_date": exit_date,
            "exit_reason": reason, "realized_return": ret, "decision_confidence": confidence}


CLOSED = [
    _closed("005930", "2026-09-10", -0.05),
    _closed("000660", "2026-09-12", 0.10, "take_profit", 0.8),
    _closed("005930", "2026-09-20", 0.02, "max_holding_days", 0.5),
    _closed("035420", "2026-10-02", -0.04),          # on the decision day: not yet known
]


def test_only_trades_closed_before_the_decision_count():
    summary = summarize_closed(CLOSED, before="2026-10-02")
    assert summary["count"] == 3 and summary["wins"] == 2
    assert summary["by_exit_reason"]["stop_loss"] == {"count": 1, "wins": 0, "hit_rate": 0.0, "average_return": -0.05}
    assert set(summary["by_confidence"]) == {"0.6 미만", "0.6~0.75", "0.75 이상"}
    assert [t["ticker_code"] for t in summary["recent"]] == ["005930", "000660", "005930"]


def test_the_text_names_this_ticker_and_warns_about_a_small_sample():
    summary = summarize_closed(CLOSED, before="2026-10-02")
    text = track_record_text(summary, "005930")
    assert "전체 3건 · 승률 67%" in text
    assert "표본 3건" in text
    assert "손절 1건" in text and "익절 1건" in text
    assert "이 종목(005930) 과거 거래" in text and "-5.00%" in text
    assert "035420" not in text
    assert "청산한 적이 없음" in track_record_text(summary, "999999")
    assert track_record_text(summarize_closed([], before="2026-10-02")) == ""


def test_every_confirmer_call_sees_the_record_and_the_run_keeps_it():
    points = _points()
    seen = []

    def confirmer(candidate, context):
        seen.append(context.get("track_record", ""))
        return Confirmation(rating="Hold", confidence=0.5, source="test")

    result = run_daily_pipeline(
        "2026-10-02",
        config=PipelineConfig(min_probability_up=0, min_expected_return=-1, mandate=TradingMandate(max_positions=5)),
        screener_runner=lambda when, cfg: _screener_result(points),
        history_fetcher=lambda code, s, e: points,
        confirmer=confirmer,
        current_prices={"005930": 70_000, "000660": 70_000},
        track_record=summarize_closed(CLOSED, before="2026-10-02"),
    )
    assert len(seen) == 2 and all("전체 3건" in text for text in seen)
    assert any("이 종목(005930) 과거 거래" in text for text in seen)
    assert any("이 종목(000660) 과거 거래" in text for text in seen)
    assert result.as_dict()["track_record"]["count"] == 3
    assert "_rows" not in result.as_dict()["track_record"]


def test_the_record_is_read_from_the_stored_fills():
    repo = _repo()
    _seed_account(repo)
    summary = build_track_record(repo, account_key="paper", before=None)
    assert summary["count"] == 1
    assert summary["by_exit_reason"]["take_profit"]["count"] == 1
    assert build_track_record(repo, account_key="paper", before="2000-01-01")["count"] == 0
    assert latest_run_id(repo, account_key="paper") is not None
    assert latest_run_id(repo, account_key="kis") is None


def test_the_review_is_given_the_real_outcomes_and_returns_proposals():
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return json.dumps({"summary": "손절이 잦음", "hit_rate": 0.67, "average_return": 0.02,
                           "what_worked": ["익절"], "what_failed": ["손절 폭"],
                           "rule_changes": ["손절 폭을 ATR 기준으로 넓히는 안 검토"]}, ensure_ascii=False)

    result = review_track_record(llm, summarize_closed(CLOSED, before="2026-10-03"), account_key="paper")
    assert result.status == "ok"
    assert result.data["rule_changes"] == ["손절 폭을 ATR 기준으로 넓히는 안 검토"]
    assert "사후 복기" in prompts[0] and "paper_outcomes" in prompts[0] and "035420" in prompts[0]

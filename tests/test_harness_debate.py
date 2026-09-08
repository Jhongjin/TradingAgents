import json

import pytest

from tradingagents.harness import DebateOutcome, build_harness_context_text, run_debate
from tradingagents.harness.pipeline import debate_confirmer
from tradingagents.screener import MarketSnapshot, MarketSnapshotRow, ScreenerConfig, screen_korean_market


def _points(count=200, drift=0.004):
    rows = []
    close = 50_000.0
    for index in range(count):
        close *= 1 + drift
        rows.append({"date": f"d{index}", "close": round(close, 2), "volume": 1_000_000})
    return rows


def _candidate():
    snapshot = MarketSnapshot(
        as_of_date="2026-09-05",
        markets=("KOSPI",),
        rows=[MarketSnapshotRow("005930", "삼성전자", "KOSPI", 70_000.0, 1e7, 5e11, 4e14, 0.5, 12.0, 1.2, 2.0)],
    )
    return screen_korean_market(snapshot=snapshot, history_fetcher=lambda c, s, e: _points(), config=ScreenerConfig(top_n=1, min_composite=-10)).candidates[0]


def _scripted_llm(responses: dict[str, dict], *, calls: list | None = None):
    def llm(prompt: str) -> str:
        if calls is not None:
            calls.append(prompt)
        for marker, payload in responses.items():
            if f"({marker})" in prompt or f"과제 " in prompt and marker in prompt:
                return json.dumps(payload, ensure_ascii=False)
        return json.dumps({"summary": "n/a", "confidence": 0.5}, ensure_ascii=False)

    return llm


BASE_RESPONSES = {
    "bull_researcher": {"thesis": "강세", "arguments": [{"claim": "모멘텀", "evidence_key": "candidate"}], "conviction": 0.8},
    "bear_researcher": {"thesis": "약세", "arguments": [{"claim": "고변동성", "evidence_key": "risk_metrics"}], "conviction": 0.4},
    "research_manager": {"recommendation": "Overweight", "rationale": "강세 우세", "strategic_actions": "분할 매수", "confidence": 0.7},
    "risk_panel": {"aggressive_view": "a", "neutral_view": "n", "conservative_view": "c", "stop_loss_pct": 0.06, "take_profit_pct": 0.12, "position_weight": 0.1, "risk_score": 0.4},
    "portfolio_manager": {"rating": "Buy", "executive_summary": "진입", "investment_thesis": "근거", "confidence": 0.75},
}


def test_run_debate_sequences_roles_and_returns_pm_rating():
    calls = []
    outcome = run_debate(_scripted_llm(BASE_RESPONSES, calls=calls), target="삼성전자", evidence={"candidate": {"rank": 1}})

    assert isinstance(outcome, DebateOutcome)
    assert outcome.rating == "Buy"
    assert outcome.confidence == 0.75
    assert outcome.stop_loss_pct == 0.06
    assert outcome.take_profit_pct == 0.12
    assert outcome.position_weight == 0.1
    assert outcome.is_bullish
    assert [turn.role for turn in (outcome.bull, outcome.bear, outcome.judge, outcome.risk_panel, outcome.portfolio_manager)] == [
        "bull_researcher",
        "bear_researcher",
        "research_manager",
        "risk_panel",
        "portfolio_manager",
    ]
    assert len(calls) == 5
    assert "[Bull r1] 강세" in calls[1]  # bear sees bull thesis
    assert "[Research Manager]" in calls[3]
    assert "[Risk Panel]" in calls[4]
    assert outcome.as_dict()["turns"]["judge"]["data"]["recommendation"] == "Overweight"


def test_run_debate_multiple_rounds_and_risk_downgrade():
    calls = []
    responses = dict(BASE_RESPONSES)
    responses["risk_panel"] = {**BASE_RESPONSES["risk_panel"], "risk_score": 0.9}
    outcome = run_debate(_scripted_llm(responses, calls=calls), target="x", evidence={}, rounds=2)
    assert len(calls) == 7
    assert outcome.rating == "Hold"
    assert any("downgraded" in warning for warning in outcome.warnings)
    with pytest.raises(ValueError):
        run_debate(_scripted_llm(responses), target="x", evidence={}, rounds=0)


def test_run_debate_falls_back_to_judge_rating_and_flags_failures():
    responses = dict(BASE_RESPONSES)
    responses["portfolio_manager"] = {"rating": "Maybe", "confidence": 0.9}
    outcome = run_debate(_scripted_llm(responses), target="x", evidence={})
    assert outcome.rating == "Overweight"
    assert any("unknown rating" in warning for warning in outcome.warnings)

    def broken(prompt):
        if "(portfolio_manager)" in prompt or "(research_manager)" in prompt:
            raise RuntimeError("llm down")
        return json.dumps(BASE_RESPONSES["bull_researcher"])

    outcome = run_debate(broken, target="x", evidence={})
    assert outcome.rating == "Hold"
    assert outcome.confidence == 0.0
    assert any("turns failed" in warning for warning in outcome.warnings)


def test_debate_confirmer_runs_playbook_then_debate():
    calls = []

    def llm(prompt):
        calls.append(prompt)
        if "## 과제" in prompt:
            return json.dumps({"summary": "기술적 강세", "action": "Buy", "confidence": 0.8, "stop_loss_pct": 0.05, "take_profit_pct": 0.1, "risk_score": 0.3}, ensure_ascii=False)
        for marker, payload in BASE_RESPONSES.items():
            if f"({marker})" in prompt:
                return json.dumps(payload, ensure_ascii=False)
        raise AssertionError(prompt)

    candidate = _candidate()
    confirmation = debate_confirmer(llm)(candidate, {"candidate": candidate.as_dict(), "chart": [], "forecast": {}, "risk_metrics": {}})
    assert confirmation.source == "debate"
    assert confirmation.rating == "Buy"
    assert confirmation.stop_loss_pct == 0.06
    assert set(confirmation.raw["playbook"]) == {"technical_analysis", "risk_management", "devils_advocate"}
    assert "기술적 강세" in calls[3]  # debate prompts embed playbook evidence
    assert len(calls) == 8


def test_debate_confirmer_raises_when_every_llm_call_fails():
    def broken(prompt):
        raise RuntimeError("Error code: 401 - invalid_api_key")

    candidate = _candidate()
    with pytest.raises(RuntimeError, match="all debate turns failed: .*401"):
        debate_confirmer(broken)(candidate, {"candidate": candidate.as_dict()})

    from tradingagents.harness.pipeline import playbook_confirmer

    with pytest.raises(RuntimeError, match="all playbook calls failed"):
        playbook_confirmer(broken)(candidate, {"candidate": candidate.as_dict()})


def test_build_harness_context_text_summarises_evidence():
    text = build_harness_context_text(
        {
            "candidate": {"rank": 2, "factors": {"composite": 0.4, "momentum_20d": 0.1, "rsi_14": 60, "labels": ["정배열 상승추세"]}},
            "forecast": {"backend": "naive", "horizon": 20, "expected_return": 0.05, "probability_up": 0.6},
            "risk_metrics": {"annualized_volatility": 0.3, "max_drawdown": -0.1, "value_at_risk_95": 0.02},
            "paper_learning": "손절 규칙 유효",
        }
    )
    assert "스크리너 순위 2" in text
    assert "정배열 상승추세" in text
    assert "상승 확률 0.6" in text
    assert "과거 가상매매 교훈" in text

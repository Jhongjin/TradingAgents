"""Structured bull/bear/judge/risk debate over harness evidence.

The full TradingAgents graph already runs a multi-round debate (bull vs bear
researchers → research manager → trader → three risk debators → portfolio
manager). That logic is sound; what it lacks is (a) deterministic evidence
injection and (b) a cheap, structured variant that the daily pipeline can run
for several candidates without a full tool-calling graph per name.

This module provides the structured variant. It reuses the same roles and the
same five-tier rating scale, takes the playbook results plus screener/forecast
data as evidence, and returns a ``DebateOutcome`` that the pipeline consumes
through ``debate_confirmer``. The heavyweight graph stays available through
``graph_confirmer`` and now receives the same evidence via ``harness_context``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from tradingagents.agents.utils.rating import RATINGS_5_TIER, parse_rating

from .tasks import LLMCallable, parse_json_output


RATING_SCALE_KO = (
    "Buy(강한 매수 확신) / Overweight(비중 확대) / Hold(관망) / Underweight(비중 축소) / Sell(매도·진입 회피)"
)


@dataclass(frozen=True)
class DebateTurn:
    role: str
    status: str
    data: dict[str, Any]
    raw_output: str = ""
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DebateOutcome:
    rating: str
    confidence: float
    rationale: str
    stop_loss_pct: float | None
    take_profit_pct: float | None
    position_weight: float | None
    bull: DebateTurn
    bear: DebateTurn
    judge: DebateTurn
    risk_panel: DebateTurn
    portfolio_manager: DebateTurn
    warnings: list[str] = field(default_factory=list)

    @property
    def is_bullish(self) -> bool:
        return self.rating in {"Buy", "Overweight"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "rating": self.rating,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "position_weight": self.position_weight,
            "turns": {
                "bull": self.bull.as_dict(),
                "bear": self.bear.as_dict(),
                "judge": self.judge.as_dict(),
                "risk_panel": self.risk_panel.as_dict(),
                "portfolio_manager": self.portfolio_manager.as_dict(),
            },
            "warnings": self.warnings,
        }


def run_debate(
    llm: LLMCallable,
    *,
    target: str,
    evidence: Mapping[str, Any],
    playbook_results: Sequence[Any] = (),
    rounds: int = 1,
) -> DebateOutcome:
    """Run bull → bear (→ rebuttal rounds) → judge → risk panel → portfolio manager."""

    if rounds <= 0:
        raise ValueError("rounds must be positive")
    evidence_text = _evidence_block(evidence, playbook_results)
    warnings: list[str] = []

    bull_history: list[str] = []
    bear_history: list[str] = []
    bull = bear = None
    for round_index in range(rounds):
        bull = _turn(
            llm,
            role="bull_researcher",
            instruction=(
                f"당신은 {target}의 강세 연구원입니다. 제공된 증거만 사용해 매수 논리를 가장 강하게 구성하세요. "
                + ("직전 약세 논거를 반박하세요. " if bear_history else "")
                + "각 주장에는 근거(증거 키)를 붙이세요."
            ),
            schema={
                "thesis": "핵심 매수 논리 3문장",
                "arguments": "주장 목록 {claim, evidence_key}",
                "rebuttal": "약세 논거에 대한 반박 (있을 때)",
                "conviction": "0~1",
            },
            evidence_text=evidence_text,
            history="\n".join(bull_history + bear_history),
        )
        bull_history.append(f"[Bull r{round_index + 1}] {bull.data.get('thesis', '')}")
        bear = _turn(
            llm,
            role="bear_researcher",
            instruction=(
                f"당신은 {target}의 약세 연구원입니다. 제공된 증거만 사용해 매수를 반대하는 논리를 가장 강하게 구성하고, 강세 연구원의 주장을 반박하세요. "
                "과대평가된 근거, 데이터 공백, 하방 시나리오를 지적하세요."
            ),
            schema={
                "thesis": "핵심 약세 논리 3문장",
                "arguments": "주장 목록 {claim, evidence_key}",
                "rebuttal": "강세 논거에 대한 반박",
                "conviction": "0~1",
            },
            evidence_text=evidence_text,
            history="\n".join(bull_history + bear_history),
        )
        bear_history.append(f"[Bear r{round_index + 1}] {bear.data.get('thesis', '')}")

    judge = _turn(
        llm,
        role="research_manager",
        instruction=(
            f"당신은 리서치 매니저입니다. 강세/약세 토론을 평가해 {target}에 대한 투자 계획을 결정하세요. "
            f"등급은 {RATING_SCALE_KO} 중 하나입니다. 양쪽 근거가 정말로 균형일 때만 Hold를 선택하세요."
        ),
        schema={
            "recommendation": "Buy/Overweight/Hold/Underweight/Sell",
            "rationale": "어느 쪽 논거가 왜 이겼는지",
            "strategic_actions": "트레이더를 위한 구체 행동 지침",
            "confidence": "0~1",
        },
        evidence_text=evidence_text,
        history="\n".join(bull_history + bear_history),
    )

    risk_panel = _turn(
        llm,
        role="risk_panel",
        instruction=(
            "당신은 공격적/중립적/보수적 리스크 분석가 세 명의 패널입니다. 리서치 매니저의 계획을 세 관점에서 각각 평가한 뒤 "
            "합의된 손절 비율, 익절 비율, 계좌 대비 포지션 비중을 제시하세요. 비중은 0~0.25 범위, 손절은 0.02~0.15 범위를 권장합니다."
        ),
        schema={
            "aggressive_view": "공격적 관점 요약",
            "neutral_view": "중립 관점 요약",
            "conservative_view": "보수적 관점 요약",
            "stop_loss_pct": "소수 (예: 0.05)",
            "take_profit_pct": "소수 (예: 0.10)",
            "position_weight": "소수 (예: 0.1)",
            "risk_score": "0(안전)~1(위험)",
        },
        evidence_text=evidence_text,
        history=f"[Research Manager] {json.dumps(judge.data, ensure_ascii=False)}",
    )

    portfolio_manager = _turn(
        llm,
        role="portfolio_manager",
        instruction=(
            f"당신은 포트폴리오 매니저입니다. 리서치 매니저 계획과 리스크 패널 결론을 종합해 {target}의 최종 등급을 결정하세요. "
            f"등급은 {RATING_SCALE_KO} 중 하나이며, 리스크 점수가 0.8 이상이면 Buy를 피하세요. 과거 교훈(있다면)을 반영하세요."
        ),
        schema={
            "rating": "Buy/Overweight/Hold/Underweight/Sell",
            "executive_summary": "진입 전략, 비중, 리스크 수준, 시계 2~4문장",
            "investment_thesis": "근거 요약",
            "confidence": "0~1",
        },
        evidence_text=evidence_text,
        history=(
            f"[Research Manager] {json.dumps(judge.data, ensure_ascii=False)}\n"
            f"[Risk Panel] {json.dumps(risk_panel.data, ensure_ascii=False)}"
        ),
    )

    rating = _rating_from(portfolio_manager, judge, warnings)
    confidence = _confidence_from(portfolio_manager, judge, bull, bear)
    risk_score = _float_or(risk_panel.data.get("risk_score"), None)
    if risk_score is not None and risk_score >= 0.8 and rating in {"Buy", "Overweight"}:
        warnings.append(f"risk panel score {risk_score:.2f} ≥ 0.8; downgraded to Hold")
        rating = "Hold"
    failed = [turn.role for turn in (bull, bear, judge, risk_panel, portfolio_manager) if turn.status != "ok"]
    if failed:
        warnings.append(f"turns failed: {', '.join(failed)}")
        if "portfolio_manager" in failed and "research_manager" in failed:
            rating = "Hold"
            confidence = 0.0
    return DebateOutcome(
        rating=rating,
        confidence=confidence,
        rationale=str(portfolio_manager.data.get("executive_summary") or judge.data.get("rationale") or ""),
        stop_loss_pct=_optional_pct(risk_panel.data.get("stop_loss_pct")),
        take_profit_pct=_optional_pct(risk_panel.data.get("take_profit_pct")),
        position_weight=_optional_pct(risk_panel.data.get("position_weight")),
        bull=bull,
        bear=bear,
        judge=judge,
        risk_panel=risk_panel,
        portfolio_manager=portfolio_manager,
        warnings=warnings,
    )


def build_harness_context_text(evidence: Mapping[str, Any], playbook_results: Sequence[Any] = ()) -> str:
    """Compact Korean text summary of harness evidence for the full graph's PM prompt."""

    lines = ["[하네스 증거 요약]"]
    candidate = evidence.get("candidate") or {}
    if candidate:
        factors = candidate.get("factors") or {}
        lines.append(
            f"- 스크리너 순위 {candidate.get('rank')}: composite {factors.get('composite')}, "
            f"20일 모멘텀 {factors.get('momentum_20d')}, RSI {factors.get('rsi_14')}, 라벨 {', '.join(factors.get('labels') or [])}"
        )
    forecast = evidence.get("forecast") or {}
    if forecast:
        lines.append(
            f"- 통계 예측({forecast.get('backend')}): {forecast.get('horizon')}일 기대수익률 {forecast.get('expected_return')}, "
            f"상승 확률 {forecast.get('probability_up')}"
        )
    metrics = evidence.get("risk_metrics") or {}
    if metrics:
        lines.append(
            f"- 리스크 지표: 연변동성 {metrics.get('annualized_volatility')}, MDD {metrics.get('max_drawdown')}, "
            f"VaR95 {metrics.get('value_at_risk_95')}"
        )
    for result in playbook_results:
        data = getattr(result, "data", None) or {}
        if getattr(result, "status", "") == "ok" and data.get("summary"):
            lines.append(f"- {getattr(result, 'title', getattr(result, 'task_id', ''))}: {data.get('summary')}")
    if evidence.get("paper_learning"):
        lines.append(f"- 과거 가상매매 교훈: {evidence['paper_learning']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- helpers
def _turn(
    llm: LLMCallable,
    *,
    role: str,
    instruction: str,
    schema: Mapping[str, str],
    evidence_text: str,
    history: str,
) -> DebateTurn:
    prompt = "\n".join(
        [
            "당신은 한국 주식 리서치 하네스의 토론 참여자입니다. 제공된 증거 밖의 가격이나 수치를 만들어내지 마세요.",
            "",
            f"## 역할 지시 ({role})",
            instruction,
            "",
            "## 증거",
            evidence_text,
            "",
            "## 토론 기록",
            history or "(없음)",
            "",
            "## 출력 JSON 스키마",
            json.dumps(dict(schema), ensure_ascii=False, indent=2),
            "",
            "JSON만 출력하세요.",
        ]
    )
    try:
        raw = llm(prompt)
    except Exception as exc:
        return DebateTurn(role=role, status="llm_error", data={}, error=f"{exc.__class__.__name__}: {exc}")
    raw_text = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
    data, error = parse_json_output(raw_text)
    return DebateTurn(role=role, status="ok" if error is None else "parse_error", data=data, raw_output=raw_text, error=error)


def _evidence_block(evidence: Mapping[str, Any], playbook_results: Sequence[Any]) -> str:
    payload: dict[str, Any] = {}
    for key, value in evidence.items():
        if value in (None, "", [], {}):
            continue
        if key == "chart" and isinstance(value, list):
            payload[key] = value[-30:]
        else:
            payload[key] = value
    if playbook_results:
        payload["playbook"] = {
            getattr(result, "task_id", str(index)): getattr(result, "data", {})
            for index, result in enumerate(playbook_results)
            if getattr(result, "status", "") == "ok"
        }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _rating_from(portfolio_manager: DebateTurn, judge: DebateTurn, warnings: list[str]) -> str:
    for turn, key in ((portfolio_manager, "rating"), (judge, "recommendation")):
        value = str(turn.data.get(key) or "").strip()
        if value:
            normalized = parse_rating(f"Rating: {value}", default="")
            if normalized in RATINGS_5_TIER:
                return normalized
            warnings.append(f"{turn.role} returned unknown rating {value!r}")
    return "Hold"


def _confidence_from(*turns: DebateTurn | None) -> float:
    for turn in turns:
        if turn is None:
            continue
        value = _float_or(turn.data.get("confidence"), None)
        if value is None:
            value = _float_or(turn.data.get("conviction"), None)
        if value is not None:
            return max(0.0, min(float(value), 1.0))
    return 0.0


def _float_or(value: Any, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_pct(value: Any) -> float | None:
    parsed = _float_or(value, None)
    if parsed is None:
        return None
    if parsed > 1:
        parsed = parsed / 100
    if not 0 < parsed < 1:
        return None
    return parsed

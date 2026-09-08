"""Daily screen → forecast → confirm → size → gate → order pipeline.

Every stage is injectable so the pipeline can run fully offline in tests and
fully live (pykrx + LLM + KIS 모의투자) in production with the same code.
Fail-closed rules:

* No confirmer configured and ``require_llm_confirmation`` is true → no orders.
* Confirmer error → that candidate is skipped, never traded.
* Mandate gate rejects → no order, reason recorded.
* ``dry_run`` (default) → orders are logged but never sent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from tradingagents.analytics import risk_summary
from tradingagents.execution import (
    AuditLedger,
    BrokerAdapter,
    BrokerOrderResult,
    KoreaTradingRules,
    MandateContext,
    MandateGate,
    OrderIntent,
    OrderSide,
    PaperBroker,
    PaperBrokerAdapter,
    PositionSizeRequest,
    RiskLimits,
    TradingMandate,
    size_position,
)
from tradingagents.forecast import ForecastResult, Forecaster, forecast_from_points, get_forecaster
from tradingagents.screener import ScreenerCandidate, ScreenerConfig, ScreenerResult, screen_korean_market

from .prompts import get_prompt
from .tasks import HarnessTask, LLMCallable, run_task


HistoryFetcher = Callable[[str, str, str], Sequence[Mapping[str, Any]]]
ScreenerRunner = Callable[[str | None, ScreenerConfig], ScreenerResult]


@dataclass(frozen=True)
class Confirmation:
    rating: str
    confidence: float
    rationale: str = ""
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    source: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_bullish(self) -> bool:
        return self.rating.strip().lower() in {"buy", "overweight"}

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


Confirmer = Callable[[ScreenerCandidate, Mapping[str, Any]], Confirmation]


@dataclass(frozen=True)
class PipelineConfig:
    markets: tuple[str, ...] = ("KOSPI", "KOSDAQ")
    screener: ScreenerConfig = field(default_factory=ScreenerConfig)
    confirm_top_n: int = 5
    forecast_horizon: int = 20
    forecast_backend: str | None = None
    min_probability_up: float = 0.55
    min_expected_return: float = 0.02
    min_confidence: float = 0.6
    risk_percent_per_trade: float = 0.01
    max_position_weight: float = 0.2
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    initial_cash: float = 10_000_000.0
    dry_run: bool = True
    require_llm_confirmation: bool = True
    mandate: TradingMandate = field(default_factory=TradingMandate)
    audit_log_path: str | None = None
    history_days: int = 200

    def __post_init__(self) -> None:
        if self.confirm_top_n <= 0:
            raise ValueError("confirm_top_n must be positive")
        if not 0 <= self.min_probability_up <= 1:
            raise ValueError("min_probability_up must be between 0 and 1")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        if not 0 < self.take_profit_pct < 1:
            raise ValueError("take_profit_pct must be between 0 and 1")


@dataclass(frozen=True)
class PipelineDecision:
    code: str
    name: str
    market: str
    stage: str  # screened | forecast_rejected | confirmation_rejected | sized | gate_rejected | ordered | exit
    reasons: list[str] = field(default_factory=list)
    screener_rank: int | None = None
    factors: dict[str, Any] | None = None
    forecast: dict[str, Any] | None = None
    risk_metrics: dict[str, Any] | None = None
    confirmation: dict[str, Any] | None = None
    sizing: dict[str, Any] | None = None
    mandate: dict[str, Any] | None = None
    order: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineRunResult:
    as_of_date: str
    mode: str
    broker: str
    dry_run: bool
    screener: dict[str, Any]
    decisions: list[PipelineDecision]
    account_before: dict[str, Any]
    account_after: dict[str, Any]
    audit_sequence_start: int | None
    audit_sequence_end: int | None
    notes: list[str] = field(default_factory=list)
    confirmer: str = "none"
    run_id: str | None = None

    @property
    def orders(self) -> list[PipelineDecision]:
        return [decision for decision in self.decisions if decision.stage in {"ordered", "exit"} and decision.order]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "as_of_date": self.as_of_date,
            "mode": self.mode,
            "broker": self.broker,
            "dry_run": self.dry_run,
            "confirmer": self.confirmer,
            "execution_boundary": "dry_run_no_orders" if self.dry_run else f"{self.broker}_orders",
            "screener": self.screener,
            "decisions": [decision.as_dict() for decision in self.decisions],
            "orders": [decision.as_dict() for decision in self.orders],
            "account_before": self.account_before,
            "account_after": self.account_after,
            "audit_sequence_start": self.audit_sequence_start,
            "audit_sequence_end": self.audit_sequence_end,
            "notes": self.notes,
        }


def run_daily_pipeline(
    as_of_date: str | date | None = None,
    *,
    config: PipelineConfig | None = None,
    screener_runner: ScreenerRunner | None = None,
    history_fetcher: HistoryFetcher | None = None,
    forecaster: Forecaster | None = None,
    confirmer: Confirmer | None = None,
    broker: BrokerAdapter | None = None,
    ledger: AuditLedger | None = None,
    current_prices: Mapping[str, float] | None = None,
    repo: Any | None = None,
    confirmer_name: str | None = None,
    visibility: str = "public",
) -> PipelineRunResult:
    """Run one cycle. When ``repo`` is given the run and decisions are persisted."""

    config = config or PipelineConfig()
    as_of = _coerce_date(as_of_date).isoformat() if as_of_date is not None else None
    ledger = ledger if ledger is not None else (AuditLedger(config.audit_log_path) if config.audit_log_path else None)
    sequence_start = ledger.sequence + 1 if ledger else None
    broker = broker or PaperBrokerAdapter(
        PaperBroker.with_limits(
            initial_cash=config.initial_cash,
            limits=RiskLimits(max_position_weight=config.max_position_weight),
            currency="KRW",
            execution_rules=KoreaTradingRules(),
        )
    )
    forecaster = forecaster or get_forecaster(config.forecast_backend)
    fetcher = history_fetcher or _chart_history_fetcher
    notes: list[str] = []

    screener_config = ScreenerConfig(**{**asdict(config.screener), "markets": tuple(config.markets)})
    runner = screener_runner or (lambda when, cfg: screen_korean_market(when, config=screener_config, history_fetcher=fetcher))
    screener_result = runner(as_of, screener_config)
    resolved_date = screener_result.as_of_date
    _audit(ledger, "screen", {"as_of_date": resolved_date, "candidates": [c.code for c in screener_result.candidates], "universe_size": screener_result.universe_size})

    account_before = broker.account_snapshot(current_prices).as_dict()
    decisions: list[PipelineDecision] = []

    # ------------------------------------------------------------- exits
    decisions.extend(_evaluate_exits(broker, config, current_prices or {}, ledger))

    # ----------------------------------------------------------- entries
    if config.require_llm_confirmation and confirmer is None:
        notes.append("no confirmer configured; require_llm_confirmation=True so no entries are placed (fail closed)")
    end_date = datetime.strptime(resolved_date, "%Y-%m-%d").date()
    start_date = end_date - timedelta(days=int(config.history_days * 1.6) + 10)
    for candidate in screener_result.candidates[: config.confirm_top_n]:
        decisions.append(
            _process_candidate(
                candidate,
                config=config,
                fetcher=fetcher,
                forecaster=forecaster,
                confirmer=confirmer,
                broker=broker,
                ledger=ledger,
                start_date=start_date.isoformat(),
                end_date=resolved_date,
                current_prices=current_prices or {},
            )
        )

    account_after = broker.account_snapshot(current_prices).as_dict()
    _audit(ledger, "cycle_complete", {"as_of_date": resolved_date, "orders": len([d for d in decisions if d.order]), "dry_run": config.dry_run})
    resolved_confirmer = confirmer_name or ("none" if confirmer is None else getattr(confirmer, "__name__", "custom"))
    result = PipelineRunResult(
        as_of_date=resolved_date,
        mode="paper" if getattr(broker, "is_paper", True) else "live",
        broker=getattr(broker, "name", "unknown"),
        dry_run=config.dry_run,
        screener={
            "universe_size": screener_result.universe_size,
            "prefiltered_size": screener_result.prefiltered_size,
            "scored_size": screener_result.scored_size,
            "candidate_count": len(screener_result.candidates),
            "candidates": [c.as_dict() for c in screener_result.candidates],
            "notes": screener_result.notes,
        },
        decisions=decisions,
        account_before=account_before,
        account_after=account_after,
        audit_sequence_start=sequence_start,
        audit_sequence_end=ledger.sequence if ledger else None,
        notes=notes,
        confirmer=resolved_confirmer,
    )
    if repo is not None:
        try:
            run_id = persist_pipeline_result(repo, result, config=config, visibility=visibility)
        except Exception as exc:
            notes.append(f"persistence failed: {exc.__class__.__name__}: {exc}")
            _audit(ledger, "persist_error", {"error": f"{exc.__class__.__name__}: {exc}"})
        else:
            _audit(ledger, "persisted", {"harness_run_id": run_id})
            result = PipelineRunResult(**{**result.__dict__, "run_id": run_id})
    return result


def persist_pipeline_result(repo: Any, result: PipelineRunResult, *, config: PipelineConfig, visibility: str = "public") -> str:
    """Store a run and its decisions through the storage repository."""

    from decimal import Decimal

    from tradingagents.storage import HarnessDecisionInput, HarnessRunInput

    as_of = _coerce_date(result.as_of_date)
    run_id = repo.create_harness_run(
        HarnessRunInput(
            as_of_date=as_of,
            mode=result.mode,
            broker=result.broker,
            dry_run=result.dry_run,
            confirmer=result.confirmer,
            visibility=visibility,
            markets=",".join(config.markets),
            universe_size=int(result.screener.get("universe_size") or 0),
            candidate_count=int(result.screener.get("candidate_count") or 0),
            order_count=len(result.orders),
            cash_before=_decimal(result.account_before.get("cash")),
            cash_after=_decimal(result.account_after.get("cash")),
            audit_sequence_start=result.audit_sequence_start,
            audit_sequence_end=result.audit_sequence_end,
            notes=[*result.notes, *result.screener.get("notes", [])],
            metadata={
                "config": {
                    "confirm_top_n": config.confirm_top_n,
                    "forecast_horizon": config.forecast_horizon,
                    "min_probability_up": config.min_probability_up,
                    "min_expected_return": config.min_expected_return,
                    "min_confidence": config.min_confidence,
                    "risk_percent_per_trade": config.risk_percent_per_trade,
                    "max_position_weight": config.max_position_weight,
                    "stop_loss_pct": config.stop_loss_pct,
                    "take_profit_pct": config.take_profit_pct,
                },
                "mandate": config.mandate.as_dict(),
                "screener_candidates": [
                    {"rank": c.get("rank"), "code": c.get("code"), "name": c.get("name"), "composite": (c.get("factors") or {}).get("composite")}
                    for c in result.screener.get("candidates", [])
                ],
            },
        )
    )
    for decision in result.decisions:
        forecast = decision.forecast or {}
        confirmation = decision.confirmation or {}
        sizing = decision.sizing or {}
        order = decision.order or {}
        repo.add_harness_decision(
            HarnessDecisionInput(
                harness_run_id=run_id,
                as_of_date=as_of,
                ticker_code=decision.code,
                ticker_name=decision.name,
                market=decision.market,
                stage=decision.stage,
                screener_rank=decision.screener_rank,
                composite_score=(decision.factors or {}).get("composite"),
                forecast_expected_return=forecast.get("expected_return"),
                forecast_probability_up=forecast.get("probability_up"),
                confirmation_rating=confirmation.get("rating"),
                confirmation_confidence=confirmation.get("confidence"),
                confirmation_source=confirmation.get("source"),
                quantity=sizing.get("quantity") or (order.get("order") or {}).get("quantity"),
                entry_price=_decimal(sizing.get("entry_price")),
                stop_price=_decimal(sizing.get("stop_price")),
                take_profit_price=_decimal(sizing.get("take_profit_price")),
                order_status=order.get("status"),
                reasons=list(decision.reasons),
                detail={
                    "factors": decision.factors,
                    "forecast": forecast,
                    "risk_metrics": decision.risk_metrics,
                    "confirmation": confirmation,
                    "sizing": sizing,
                    "mandate": decision.mandate,
                    "order": order,
                },
            )
        )
    return run_id


def _decimal(value: Any):
    from decimal import Decimal

    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001"))
    except Exception:
        return None


def _process_candidate(
    candidate: ScreenerCandidate,
    *,
    config: PipelineConfig,
    fetcher: HistoryFetcher,
    forecaster: Forecaster,
    confirmer: Confirmer | None,
    broker: BrokerAdapter,
    ledger: AuditLedger | None,
    start_date: str,
    end_date: str,
    current_prices: Mapping[str, float],
) -> PipelineDecision:
    base = {
        "code": candidate.code,
        "name": candidate.name,
        "market": candidate.market,
        "screener_rank": candidate.rank,
        "factors": candidate.factors.as_dict(),
    }
    try:
        points = list(fetcher(candidate.code, start_date, end_date))
    except Exception as exc:
        return PipelineDecision(stage="screened", reasons=[f"history unavailable: {exc}"], **base)
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    if len(closes) < 2:
        return PipelineDecision(stage="screened", reasons=["insufficient history"], **base)
    entry_price = float(current_prices.get(candidate.code) or closes[-1])

    # forecast gate
    try:
        forecast = forecast_from_points(points, horizon=config.forecast_horizon, forecaster=forecaster)
    except Exception as exc:
        forecast = None
        forecast_reason = f"forecast failed: {exc}"
    else:
        forecast_reason = None
    metrics = risk_summary(closes).as_dict()
    base["forecast"] = forecast.as_dict() if forecast else None
    base["risk_metrics"] = metrics
    if forecast is None:
        _audit(ledger, "forecast_error", {"code": candidate.code, "error": forecast_reason})
        return PipelineDecision(stage="forecast_rejected", reasons=[forecast_reason or "forecast unavailable"], **base)
    forecast_reasons = _forecast_gate(forecast, config)
    _audit(ledger, "forecast", {"code": candidate.code, "backend": forecast.backend, "expected_return": forecast.expected_return, "probability_up": forecast.probability_up, "passed": not forecast_reasons})
    if forecast_reasons:
        return PipelineDecision(stage="forecast_rejected", reasons=forecast_reasons, **base)

    # LLM confirmation gate
    confirmation: Confirmation | None = None
    if confirmer is not None:
        context = {
            "candidate": candidate.as_dict(),
            "chart": points[-60:],
            "forecast": forecast.as_dict(),
            "risk_metrics": metrics,
            "entry_price": entry_price,
        }
        try:
            confirmation = confirmer(candidate, context)
        except Exception as exc:
            _audit(ledger, "confirmation_error", {"code": candidate.code, "error": f"{exc.__class__.__name__}: {exc}"})
            return PipelineDecision(stage="confirmation_rejected", reasons=[f"confirmer error (fail closed): {exc}"], **base)
        base["confirmation"] = confirmation.as_dict()
        _audit(ledger, "confirmation", {"code": candidate.code, "rating": confirmation.rating, "confidence": confirmation.confidence, "source": confirmation.source})
        rejection = _confirmation_gate(confirmation, config)
        if rejection:
            return PipelineDecision(stage="confirmation_rejected", reasons=rejection, **base)
    elif config.require_llm_confirmation:
        return PipelineDecision(stage="confirmation_rejected", reasons=["no confirmer configured (fail closed)"], **base)

    # sizing
    snapshot = broker.account_snapshot(current_prices)
    stop_pct = (confirmation.stop_loss_pct if confirmation and confirmation.stop_loss_pct else None) or config.stop_loss_pct
    take_pct = (confirmation.take_profit_pct if confirmation and confirmation.take_profit_pct else None) or config.take_profit_pct
    stop_price = round(entry_price * (1 - stop_pct), 2)
    take_profit_price = round(entry_price * (1 + take_pct), 2)
    try:
        plan = size_position(
            PositionSizeRequest(
                ticker=candidate.code,
                equity=snapshot.equity,
                entry_price=entry_price,
                stop_price=stop_price,
                risk_percent_per_trade=config.risk_percent_per_trade,
                max_position_weight=min(config.max_position_weight, config.mandate.max_position_weight),
                available_cash=snapshot.cash,
                take_profit_price=take_profit_price,
            )
        )
    except ValueError as exc:
        return PipelineDecision(stage="sized", reasons=[f"sizing failed: {exc}"], **base)
    base["sizing"] = plan.as_dict()
    if plan.quantity <= 0:
        return PipelineDecision(stage="sized", reasons=["sizing produced zero quantity", *plan.notes], **base)

    # mandate gate
    order = OrderIntent(
        ticker=candidate.code,
        side=OrderSide.BUY,
        quantity=plan.quantity,
        reason=f"harness entry rank={candidate.rank} rating={confirmation.rating if confirmation else 'deterministic'}",
    )
    gate = MandateGate(config.mandate).evaluate(
        order,
        MandateContext(
            equity=snapshot.equity,
            cash=snapshot.cash,
            positions={code: item["market_value"] for code, item in snapshot.positions.items()},
            price=entry_price,
        ),
    )
    base["mandate"] = gate.as_dict()
    _audit(ledger, "mandate", {"code": candidate.code, "approved": gate.approved, "reasons": gate.reasons})
    if not gate.approved:
        return PipelineDecision(stage="gate_rejected", reasons=gate.reasons, **base)

    result = broker.place_order(order, price=entry_price, dry_run=config.dry_run)
    base["order"] = result.as_dict()
    _audit(ledger, "order", {"code": candidate.code, "status": result.status, "quantity": order.quantity, "price": entry_price, "dry_run": config.dry_run, "broker": result.broker})
    return PipelineDecision(stage="ordered", reasons=[result.message], **base)


def _evaluate_exits(
    broker: BrokerAdapter,
    config: PipelineConfig,
    current_prices: Mapping[str, float],
    ledger: AuditLedger | None,
) -> list[PipelineDecision]:
    decisions: list[PipelineDecision] = []
    snapshot = broker.account_snapshot(current_prices)
    for code, item in snapshot.positions.items():
        quantity = int(item.get("quantity") or 0)
        average = float(item.get("average_price") or 0.0)
        price = float(current_prices.get(code) or 0.0)
        if quantity <= 0 or average <= 0 or price <= 0:
            continue
        move = (price / average) - 1
        reason = None
        if move <= -config.stop_loss_pct:
            reason = "stop_loss"
        elif move >= config.take_profit_pct:
            reason = "take_profit"
        if reason is None:
            continue
        order = OrderIntent(ticker=code, side=OrderSide.SELL, quantity=quantity, reason=f"harness exit {reason} move={move:.4f}")
        gate = MandateGate(config.mandate).evaluate(
            order,
            MandateContext(
                equity=snapshot.equity,
                cash=snapshot.cash,
                positions={c: i["market_value"] for c, i in snapshot.positions.items()},
                price=price,
            ),
        )
        if not gate.approved:
            decisions.append(PipelineDecision(code=code, name=code, market="KR", stage="gate_rejected", reasons=gate.reasons, mandate=gate.as_dict()))
            continue
        result = broker.place_order(order, price=price, dry_run=config.dry_run)
        _audit(ledger, "exit_order", {"code": code, "reason": reason, "move": move, "status": result.status, "dry_run": config.dry_run})
        decisions.append(PipelineDecision(code=code, name=code, market="KR", stage="exit", reasons=[reason, result.message], mandate=gate.as_dict(), order=result.as_dict()))
    return decisions


def _forecast_gate(forecast: ForecastResult, config: PipelineConfig) -> list[str]:
    reasons: list[str] = []
    if forecast.expected_return is not None and forecast.expected_return < config.min_expected_return:
        reasons.append(f"expected return {forecast.expected_return:+.2%} below {config.min_expected_return:+.2%}")
    if forecast.probability_up is not None and forecast.probability_up < config.min_probability_up:
        reasons.append(f"probability up {forecast.probability_up:.0%} below {config.min_probability_up:.0%}")
    return reasons


def _confirmation_gate(confirmation: Confirmation, config: PipelineConfig) -> list[str]:
    reasons: list[str] = []
    if not confirmation.is_bullish:
        reasons.append(f"confirmer rating {confirmation.rating} is not bullish")
    if confirmation.confidence < config.min_confidence:
        reasons.append(f"confidence {confirmation.confidence:.2f} below {config.min_confidence:.2f}")
    return reasons


# ------------------------------------------------------------------ confirmers
def playbook_confirmer(llm: LLMCallable, *, prompt_ids: Sequence[str] = ("technical_analysis", "risk_management")) -> Confirmer:
    """Confirm a candidate with playbook prompts (cheap, structured, auditable)."""

    def _confirm(candidate: ScreenerCandidate, context: Mapping[str, Any]) -> Confirmation:
        values = {"target": f"{candidate.name}({candidate.code}, {candidate.market})", "strategy": "스크리너 후보 확인 후 손절/익절 규칙 기반 스윙"}
        results = {}
        for prompt_id in prompt_ids:
            prompt = get_prompt(prompt_id)
            task_context = {key: context[key] for key in prompt.context_keys if key in context}
            task_context["candidate"] = context.get("candidate")
            results[prompt_id] = run_task(HarnessTask(prompt=prompt, values=values, context=task_context), llm)
        technical = results.get("technical_analysis")
        risk = results.get("risk_management")
        rating = "Hold"
        confidence = 0.0
        rationale = ""
        if technical and technical.status == "ok":
            action = str(technical.data.get("action") or "Hold")
            rating = {"buy": "Buy", "sell": "Sell"}.get(action.strip().lower(), "Hold")
            confidence = _float_or(technical.data.get("confidence"), 0.0)
            score = technical.data.get("technical_score")
            if score is not None and confidence == 0.0:
                confidence = _float_or(score, 0.0)
            rationale = str(technical.data.get("summary") or "")
        stop = take = None
        if risk and risk.status == "ok":
            stop = _optional_pct(risk.data.get("stop_loss_pct"))
            take = _optional_pct(risk.data.get("take_profit_pct"))
            risk_score = _float_or(risk.data.get("risk_score"), None)
            if risk_score is not None and risk_score >= 0.8 and rating == "Buy":
                rating = "Hold"
                rationale = f"{rationale} (risk_score {risk_score:.2f} too high)".strip()
        return Confirmation(
            rating=rating,
            confidence=max(0.0, min(confidence, 1.0)),
            rationale=rationale,
            stop_loss_pct=stop,
            take_profit_pct=take,
            source="playbook",
            raw={key: value.as_dict() for key, value in results.items()},
        )

    return _confirm


def debate_confirmer(
    llm: LLMCallable,
    *,
    playbook_prompt_ids: Sequence[str] = ("technical_analysis", "risk_management", "devils_advocate"),
    rounds: int = 1,
) -> Confirmer:
    """Confirm with the structured bull/bear/judge/risk/PM debate (mid-cost).

    Playbook prompts run first to build evidence, then the debate decides. This
    mirrors the full graph's role sequence without tool-calling overhead.
    """

    from .debate import run_debate

    def _confirm(candidate: ScreenerCandidate, context: Mapping[str, Any]) -> Confirmation:
        target = f"{candidate.name}({candidate.code}, {candidate.market})"
        values = {"target": target, "strategy": "스크리너 후보 확인 후 손절/익절 규칙 기반 스윙"}
        results = []
        for prompt_id in playbook_prompt_ids:
            prompt = get_prompt(prompt_id)
            task_context = {key: context[key] for key in prompt.context_keys if key in context}
            task_context["candidate"] = context.get("candidate")
            if results:
                task_context["previous_conclusions"] = {r.task_id: r.data.get("summary") for r in results if r.status == "ok"}
            results.append(run_task(HarnessTask(prompt=prompt, values=values, context=task_context), llm))
        outcome = run_debate(llm, target=target, evidence=context, playbook_results=results, rounds=rounds)
        return Confirmation(
            rating=outcome.rating,
            confidence=outcome.confidence,
            rationale=outcome.rationale,
            stop_loss_pct=outcome.stop_loss_pct,
            take_profit_pct=outcome.take_profit_pct,
            source="debate",
            raw={"debate": outcome.as_dict(), "playbook": {r.task_id: r.as_dict() for r in results}},
        )

    return _confirm


def graph_confirmer(
    graph_factory: Callable[..., Any],
    *,
    trade_date: str | None = None,
    inject_harness_context: bool = True,
) -> Confirmer:
    """Confirm with the full TradingAgents multi-agent graph (expensive, deepest).

    ``graph_factory`` may accept a ``harness_context`` keyword; when it does,
    the deterministic evidence summary is passed so the Portfolio Manager sees
    screener rank, forecast band, and risk metrics alongside the debate.
    """

    import inspect

    from tradingagents.agents.utils.rating import parse_rating

    from .debate import build_harness_context_text

    def _confirm(candidate: ScreenerCandidate, context: Mapping[str, Any]) -> Confirmation:
        kwargs: dict[str, Any] = {}
        if inject_harness_context:
            try:
                accepts = "harness_context" in inspect.signature(graph_factory).parameters
            except (TypeError, ValueError):
                accepts = False
            if accepts:
                kwargs["harness_context"] = build_harness_context_text(context)
        graph = graph_factory(**kwargs)
        when = trade_date or datetime.now().date().isoformat()
        final_state, decision = graph.propagate(candidate.code, when)
        rating = parse_rating(str(decision or final_state.get("final_trade_decision") or ""))
        return Confirmation(
            rating=rating,
            confidence=0.7 if rating in {"Buy", "Sell"} else 0.5,
            rationale=str(final_state.get("final_trade_decision") or "")[:2000],
            source="trading_graph",
            raw={"analysis_run_id": getattr(graph, "last_analysis_run_id", None)},
        )

    return _confirm


# ------------------------------------------------------------------- helpers
def _chart_history_fetcher(code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    from tradingagents.dataflows.chart_data import get_ohlcv_chart_series

    series = get_ohlcv_chart_series(code, start_date, end_date, vendor="pykrx")
    return [point.as_dict() for point in series.points]


def _audit(ledger: AuditLedger | None, event_type: str, payload: Mapping[str, Any]) -> None:
    if ledger is None:
        return
    ledger.append(event_type, payload)


def _coerce_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


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

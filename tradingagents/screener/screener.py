"""Rule-based Korean stock screener producing ranked, explainable candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
from tradingagents.dataflows.errors import VendorUnavailableError

from .factors import FactorScores, compute_factor_scores
from .universe import (
    MarketSnapshot,
    MarketSnapshotRow,
    build_snapshot_from_history,
    fallback_universe_codes,
    load_market_snapshot,
    load_naver_market_snapshot,
)


HistoryFetcher = Callable[[str, str, str], Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class ScreenerConfig:
    markets: tuple[str, ...] = ("KOSPI", "KOSDAQ")
    min_market_cap: float = 100_000_000_000.0  # 1,000억원
    min_trading_value: float = 1_000_000_000.0  # 10억원 일 거래대금
    min_price: float = 1_000.0
    max_per: float | None = 60.0
    max_pbr: float | None = 10.0
    exclude_negative_per: bool = False
    history_days: int = 200
    prefilter_limit: int = 150
    top_n: int = 20
    factor_weights: dict[str, float] = field(default_factory=dict)
    min_composite: float = 0.0
    allow_fallback_universe: bool = True
    # "auto": pykrx whole-market frames → Naver market-cap ranking → bounded universe.
    # "pykrx": whole-market pykrx frames only (plus bounded fallback).
    # "naver": Naver market-cap ranking pages (top N per market, works on
    #          serverless and corporate networks where data.krx.co.kr is blocked).
    # "fallback": skip remote snapshots entirely and use the bounded universe.
    snapshot_mode: str = "auto"
    # Rows per market for the Naver ranking (KOSPI200/KOSDAQ150-sized by default).
    universe_size: int | None = None
    # Stop fetching history after this many seconds and rank what was scored.
    time_budget_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.top_n <= 0:
            raise ValueError("top_n must be positive")
        if self.prefilter_limit <= 0:
            raise ValueError("prefilter_limit must be positive")
        if self.history_days < 30:
            raise ValueError("history_days must be at least 30")


@dataclass(frozen=True)
class ScreenerCandidate:
    rank: int
    code: str
    name: str
    market: str
    close: float
    market_cap: float | None
    trading_value: float | None
    per: float | None
    pbr: float | None
    dividend_yield: float | None
    factors: FactorScores
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["factors"] = self.factors.as_dict()
        return payload


@dataclass(frozen=True)
class ScreenerResult:
    as_of_date: str
    markets: tuple[str, ...]
    universe_size: int
    prefiltered_size: int
    scored_size: int
    candidates: list[ScreenerCandidate]
    config: ScreenerConfig
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date,
            "markets": list(self.markets),
            "universe_size": self.universe_size,
            "prefiltered_size": self.prefiltered_size,
            "scored_size": self.scored_size,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "config": asdict(self.config),
            "notes": self.notes,
            "execution_boundary": "screening_only_no_orders",
        }


def screen_korean_market(
    as_of_date: str | date | None = None,
    *,
    config: ScreenerConfig | None = None,
    snapshot: MarketSnapshot | None = None,
    history_fetcher: HistoryFetcher | None = None,
    snapshot_loader: Callable[..., MarketSnapshot] | None = None,
) -> ScreenerResult:
    """Screen KOSPI/KOSDAQ for candidates with favourable, explainable setups.

    Stage 1 (snapshot pre-filter) removes illiquid, tiny, or extreme-valuation
    names using one whole-market frame per market. Stage 2 fetches daily
    history for the survivors and ranks them on factor scores. No LLM is used;
    the harness feeds the ranked list into the multi-agent confirmation step.
    """

    import time

    config = config or ScreenerConfig()
    started = time.monotonic()
    fetcher = history_fetcher or _chart_history_fetcher
    fallback_note: str | None = None
    history_cache: dict[str, Sequence[Mapping[str, Any]]] = {}

    def cached_fetcher(code: str, start: str, end: str) -> Sequence[Mapping[str, Any]]:
        if code not in history_cache:
            history_cache[code] = fetcher(code, start, end)
        return history_cache[code]

    snapshot_mode = _resolve_snapshot_mode(config.snapshot_mode)
    if snapshot is None:
        if snapshot_mode == "fallback":
            if not config.allow_fallback_universe:
                raise VendorUnavailableError("snapshot_mode=fallback requires allow_fallback_universe=True")
            codes = fallback_universe_codes()
            snapshot = build_snapshot_from_history(codes, as_of_date, cached_fetcher, markets=config.markets, lookback_days=int(config.history_days * 1.6) + 10)
            fallback_note = f"snapshot_mode=fallback: used bounded universe of {len(codes)} tickers (market cap/PER filters skipped)"
        else:
            errors: list[str] = []
            universe_size = config.universe_size or _resolve_universe_size()
            if snapshot_loader is not None:
                loaders = [("custom", lambda: snapshot_loader(as_of_date, markets=config.markets))]
            else:
                loaders = []
                if snapshot_mode in {"auto", "pykrx"}:
                    loaders.append(("pykrx", lambda: load_market_snapshot(as_of_date, markets=config.markets)))
                if snapshot_mode in {"auto", "naver"}:
                    loaders.append(("naver", lambda: load_naver_market_snapshot(as_of_date, markets=config.markets, max_rows_per_market=universe_size)))
            for vendor_name, loader in loaders:
                try:
                    snapshot = loader()
                    break
                except VendorUnavailableError as exc:
                    errors.append(f"{vendor_name}: {str(exc)[:120]}")
            if snapshot is None:
                if not config.allow_fallback_universe:
                    raise VendorUnavailableError("; ".join(errors) or "no snapshot loader succeeded")
                codes = fallback_universe_codes()
                snapshot = build_snapshot_from_history(codes, as_of_date, cached_fetcher, markets=config.markets, lookback_days=int(config.history_days * 1.6) + 10)
                fallback_note = (
                    f"whole-market snapshot unavailable ({'; '.join(errors)[:200]}); "
                    f"used fallback universe of {len(codes)} tickers (market cap/PER filters skipped)"
                )
    end_date = datetime.strptime(snapshot.as_of_date, "%Y-%m-%d").date()
    start_date = end_date - timedelta(days=int(config.history_days * 1.6) + 10)

    prefiltered = _prefilter(snapshot.rows, config)
    notes = [
        f"snapshot {snapshot.as_of_date} from {snapshot.vendor}",
        f"prefilter kept {len(prefiltered)} of {len(snapshot.rows)} rows",
    ]
    if fallback_note:
        notes.append(fallback_note)
    scored: list[tuple[MarketSnapshotRow, FactorScores]] = []
    failures = 0
    skipped_for_time = 0
    for index, row in enumerate(prefiltered):
        if config.time_budget_seconds is not None and (time.monotonic() - started) > config.time_budget_seconds and row.code not in history_cache:
            skipped_for_time = len(prefiltered) - index
            break
        try:
            points = cached_fetcher(row.code, start_date.isoformat(), end_date.isoformat())
        except Exception:
            failures += 1
            continue
        factors = compute_factor_scores(points, weights=config.factor_weights)
        if factors.momentum_20d is None:
            continue
        scored.append((row, factors))
    if failures:
        notes.append(f"history unavailable for {failures} rows")
    if skipped_for_time:
        notes.append(f"time budget {config.time_budget_seconds}s reached; {skipped_for_time} rows not scored")

    scored.sort(key=lambda item: item[1].composite, reverse=True)
    candidates: list[ScreenerCandidate] = []
    for row, factors in scored:
        if factors.composite < config.min_composite:
            continue
        if len(candidates) >= config.top_n:
            break
        candidates.append(
            ScreenerCandidate(
                rank=len(candidates) + 1,
                code=row.code,
                name=row.name,
                market=row.market,
                close=row.close,
                market_cap=row.market_cap,
                trading_value=row.trading_value,
                per=row.per,
                pbr=row.pbr,
                dividend_yield=row.dividend_yield,
                factors=factors,
                reasons=_reasons(row, factors),
            )
        )
    return ScreenerResult(
        as_of_date=snapshot.as_of_date,
        markets=snapshot.markets,
        universe_size=len(snapshot.rows),
        prefiltered_size=len(prefiltered),
        scored_size=len(scored),
        candidates=candidates,
        config=config,
        notes=notes,
    )


def _resolve_snapshot_mode(value: str | None) -> str:
    import os

    selected = (value or "auto").strip().lower()
    if selected == "auto":
        selected = (os.getenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE") or "auto").strip().lower()
    if selected not in {"auto", "pykrx", "naver", "fallback"}:
        raise ValueError("snapshot_mode must be 'auto', 'pykrx', 'naver', or 'fallback'")
    return selected


def _resolve_universe_size() -> int:
    import os

    raw = os.getenv("TRADINGAGENTS_SCREENER_UNIVERSE_SIZE", "150")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("TRADINGAGENTS_SCREENER_UNIVERSE_SIZE must be an integer") from exc
    if value <= 0:
        raise ValueError("TRADINGAGENTS_SCREENER_UNIVERSE_SIZE must be positive")
    return value


def _prefilter(rows: Sequence[MarketSnapshotRow], config: ScreenerConfig) -> list[MarketSnapshotRow]:
    kept: list[MarketSnapshotRow] = []
    for row in rows:
        if row.close < config.min_price:
            continue
        if row.market_cap is not None and row.market_cap < config.min_market_cap:
            continue
        if row.trading_value is not None and row.trading_value < config.min_trading_value:
            continue
        if row.per is not None:
            if config.exclude_negative_per and row.per <= 0:
                continue
            if config.max_per is not None and row.per > config.max_per:
                continue
        if row.pbr is not None and config.max_pbr is not None and row.pbr > config.max_pbr:
            continue
        kept.append(row)
    kept.sort(key=lambda row: (row.trading_value or 0.0), reverse=True)
    return kept[: config.prefilter_limit]


def _reasons(row: MarketSnapshotRow, factors: FactorScores) -> list[str]:
    reasons = list(factors.labels)
    if row.per is not None and 0 < row.per <= 12:
        reasons.append(f"PER {row.per:.1f} 저평가 구간")
    if row.pbr is not None and 0 < row.pbr <= 1.0:
        reasons.append(f"PBR {row.pbr:.2f} 청산가치 이하")
    if row.dividend_yield is not None and row.dividend_yield >= 3.0:
        reasons.append(f"배당수익률 {row.dividend_yield:.1f}%")
    return reasons


def _chart_history_fetcher(code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    series = get_ohlcv_chart_series(code, start_date, end_date, vendor="pykrx")
    return [point.as_dict() for point in series.points]

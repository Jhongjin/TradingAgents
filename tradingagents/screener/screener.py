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
    load_index_snapshot,
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
    prefilter_limit: int = 400
    top_n: int = 20
    factor_weights: dict[str, float] = field(default_factory=dict)
    min_composite: float = 0.0
    allow_fallback_universe: bool = True
    # "auto": pykrx whole-market frames → Naver market-cap ranking → bounded universe.
    # "pykrx": whole-market pykrx frames only (plus bounded fallback).
    # "naver": Naver market-cap ranking pages (top N per market, works on
    #          serverless and corporate networks where data.krx.co.kr is blocked).
    # "index": KOSPI200 constituents (Naver) + KOSDAQ150 (KRX account) or its
    #          top-150 market-cap proxy — the full index universe.
    # "fallback": skip remote snapshots entirely and use the bounded universe.
    snapshot_mode: str = "auto"
    # Rows per market for the Naver ranking (KOSPI200/KOSDAQ150-sized by default).
    universe_size: int | None = None
    # Stop fetching history after this many seconds and rank what was scored.
    time_budget_seconds: float | None = None
    # Concurrent history fetches (I/O bound); 1 disables the thread pool.
    max_workers: int = 8

    def __post_init__(self) -> None:
        if self.top_n <= 0:
            raise ValueError("top_n must be positive")
        if self.prefilter_limit <= 0:
            raise ValueError("prefilter_limit must be positive")
        if self.history_days < 30:
            raise ValueError("history_days must be at least 30")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")


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



def _fallback_codes(universe_size: int) -> tuple[list[str], str]:
    """The universe to use when no ranking vendor will answer.

    The stored index membership comes first because it is the real KOSPI200 and
    KOSDAQ150 and costs nothing to read, where the built-in seed is a handful of
    names someone typed once. It is ordered by index weight, so a cap keeps the
    part of the market that moves it rather than an arbitrary slice.
    """

    import os

    from tradingagents.dataflows.kr_tickers import is_kr_ticker, normalize_kr_ticker

    # An explicit list wins. Someone set TRADINGAGENTS_SCREENER_UNIVERSE to say
    # "screen exactly these", and quietly screening something else instead would
    # be the worst of the three outcomes here.
    raw = os.getenv("TRADINGAGENTS_SCREENER_UNIVERSE", "")
    chosen = [normalize_kr_ticker(part.strip()) for part in raw.split(",")
              if part.strip() and is_kr_ticker(part.strip())]
    if chosen:
        return list(dict.fromkeys(chosen)), "fallback universe"

    # Then the real index, which needs no vendor because it ships with the repo.
    # This deliberately outranks TRADINGAGENTS_SITEMAP_TICKERS: that variable
    # exists to list pages for a sitemap, and its use as a screening universe is
    # reuse of whatever happened to be there rather than a choice about screening.
    try:
        from tradingagents.dataflows.kr_index_members import index_universe

        members = index_universe(limit=max(int(universe_size), 1))
        if members:
            return [code for code, _ in members], "stored index membership"
    except Exception:                               # noqa: BLE001 - a missing file is not an error
        pass
    return list(fallback_universe_codes()), "fallback universe"


def screen_korean_market(
    as_of_date: str | date | None = None,
    *,
    config: ScreenerConfig | None = None,
    snapshot: MarketSnapshot | None = None,
    history_fetcher: HistoryFetcher | None = None,
    snapshot_loader: Callable[..., MarketSnapshot] | None = None,
    valuations: Mapping[str, Mapping[str, Any]] | None = None,
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
            # Same universe the automatic fallback uses. Two different answers
            # to "no vendor is available" is the kind of difference that turns
            # into a bug report nobody can reproduce.
            codes, source = _fallback_codes(config.universe_size or _resolve_universe_size())
            snapshot = build_snapshot_from_history(codes, as_of_date, cached_fetcher, markets=config.markets, lookback_days=int(config.history_days * 1.6) + 10)
            fallback_note = f"snapshot_mode=fallback: used {source} of {len(codes)} tickers (market cap/PER filters skipped)"
        else:
            errors: list[str] = []
            universe_size = config.universe_size or _resolve_universe_size()
            if snapshot_loader is not None:
                loaders = [("custom", lambda: snapshot_loader(as_of_date, markets=config.markets))]
            else:
                loaders = []
                if snapshot_mode in {"auto", "pykrx"}:
                    loaders.append(("pykrx", lambda: load_market_snapshot(as_of_date, markets=config.markets)))
                if snapshot_mode == "index":
                    loaders.append(("index", lambda: load_index_snapshot(as_of_date, markets=config.markets)))
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

                # Every ranking vendor is refused on this network — which is the
                # normal state on Vercel, where both data.krx.co.kr and Naver's
                # ranking are blocked. The stored index membership needs no
                # vendor at all: it ships with the repository. Per-ticker history
                # still works here, which is what the old six-name fallback was
                # already relying on, so the only thing that changes is how many
                # names get looked at.
                codes, source = _fallback_codes(universe_size)
                snapshot = build_snapshot_from_history(codes, as_of_date, cached_fetcher, markets=config.markets, lookback_days=int(config.history_days * 1.6) + 10)
                fallback_note = (
                    f"whole-market snapshot unavailable ({'; '.join(errors)[:200]}); "
                    f"used {source} of {len(codes)} tickers (market cap/PER filters skipped)"
                )
    end_date = datetime.strptime(snapshot.as_of_date, "%Y-%m-%d").date()
    start_date = end_date - timedelta(days=int(config.history_days * 1.6) + 10)

    rows, priced = _attach_valuations(snapshot.rows, valuations)
    prefiltered = _prefilter(rows, config)
    notes = [
        f"snapshot {snapshot.as_of_date} from {snapshot.vendor}",
        f"prefilter kept {len(prefiltered)} of {len(rows)} rows",
        # The config carries PER and PBR limits, so say plainly whether they
        # were in a position to exclude anything. Advertising a filter that
        # silently passes everything is worse than not having one.
        f"PER·PBR 한도 적용: {priced}/{len(rows)}종목에 지표 있음"
        if priced
        else "PER·PBR 지표 없음: 밸류에이션 한도 미적용",
    ]
    if fallback_note:
        notes.append(fallback_note)
    scored: list[tuple[MarketSnapshotRow, FactorScores]] = []
    failures = 0
    skipped_for_time = 0
    histories = _fetch_histories(
        prefiltered,
        cached_fetcher,
        start_date.isoformat(),
        end_date.isoformat(),
        max_workers=config.max_workers,
        deadline=(started + config.time_budget_seconds) if config.time_budget_seconds is not None else None,
    )
    for row in prefiltered:
        outcome = histories.get(row.code)
        if outcome is None:
            skipped_for_time += 1
            continue
        points, error = outcome
        if error is not None:
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


def _fetch_histories(
    rows: Sequence[MarketSnapshotRow],
    fetcher: HistoryFetcher,
    start: str,
    end: str,
    *,
    max_workers: int,
    deadline: float | None,
) -> dict[str, tuple[Sequence[Mapping[str, Any]], Exception | None]]:
    """Fetch daily history for every row, concurrently, honouring the time budget.

    Returns ``code -> (points, error)``; rows missing from the result were not
    attempted before the deadline. Results are collected in submission order
    so ranking stays deterministic for equal scores.
    """

    import time
    from concurrent.futures import ThreadPoolExecutor, wait

    results: dict[str, tuple[Sequence[Mapping[str, Any]], Exception | None]] = {}
    if not rows:
        return results

    def load(code: str):
        try:
            return code, (fetcher(code, start, end), None)
        except Exception as exc:  # vendor errors are per-row, never fatal
            return code, ([], exc)

    workers = max(1, min(max_workers, len(rows)))
    if workers == 1:
        for row in rows:
            if deadline is not None and time.monotonic() > deadline:
                break
            code, outcome = load(row.code)
            results[code] = outcome
        return results

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="screener") as pool:
        pending = {pool.submit(load, row.code): row.code for row in rows}
        while pending:
            timeout = None if deadline is None else max(deadline - time.monotonic(), 0.0)
            done, _ = wait(list(pending), timeout=timeout)
            for future in done:
                pending.pop(future, None)
                code, outcome = future.result()
                results[code] = outcome
            if not done:  # deadline hit: abandon what has not started yet
                for future in list(pending):
                    if future.cancel():
                        pending.pop(future, None)
                if pending:  # in-flight fetches finish, then we stop
                    for future in wait(list(pending)).done:
                        code, outcome = future.result()
                        results[code] = outcome
                break
    return results


def _resolve_snapshot_mode(value: str | None) -> str:
    import os

    selected = (value or "auto").strip().lower()
    if selected == "auto":
        selected = (os.getenv("TRADINGAGENTS_SCREENER_SNAPSHOT_MODE") or "auto").strip().lower()
    if selected not in {"auto", "pykrx", "naver", "index", "fallback"}:
        raise ValueError("snapshot_mode must be 'auto', 'pykrx', 'naver', 'index', or 'fallback'")
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


def _attach_valuations(
    rows: Sequence[MarketSnapshotRow],
    valuations: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[list[MarketSnapshotRow], int]:
    """Fill in PER, PBR and yield from a lookup, and count what got filled.

    The market-cap ranking that builds the universe carries no valuation
    ratios. Without them the PER and PBR limits compare against nothing and
    pass every row, so the count comes back too and the notes say so.
    """

    from dataclasses import replace

    filled: list[MarketSnapshotRow] = []
    priced = 0
    for row in rows:
        ratios = (valuations or {}).get(row.code) or {}
        per = row.per if row.per is not None else ratios.get("per")
        pbr = row.pbr if row.pbr is not None else ratios.get("pbr")
        yield_ = row.dividend_yield if row.dividend_yield is not None else ratios.get("dividend_yield")
        if per is not None or pbr is not None:
            priced += 1
        filled.append(replace(row, per=per, pbr=pbr, dividend_yield=yield_))
    return filled, priced


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

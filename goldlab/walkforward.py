"""Statistics that could have been known at the time, and that admit what luck does.

The original study counts every pattern across all the bars it has, then quotes
the result back on those same bars. That has two flaws. A signal at time t is
described by outcomes that include t's own future. And with thirty patterns and
four horizons, a handful of cells will look like edges by luck alone.

This module fixes both.

Walk-forward. The record for a signal at bar t uses only earlier signals whose
outcome had finished by t (signal bar + horizon <= t). The window is expanding,
not rolling: a pattern fires tens of times a month at best, and a rolling year
would push most cells under the sample floor before regime drift could matter.
``window_bars`` is there to try a rolling window and see whether the answer moves.

Conditioning. The same record is split by session, trend, volatility and
nearness to a release. A split is used only when it has MIN_OCCURRENCES samples;
otherwise the pooled number stands and says so.

Shrinkage. A win rate from 31 samples is mostly noise. Each is pulled toward the
base rate of the same bars by a beta-binomial prior whose strength is estimated
from how much real dispersion the patterns show beyond sampling noise
(empirical Bayes). If the patterns together show none, every edge shrinks to
zero, which is the honest answer. The ledger's as-of claims use a fixed prior,
because re-estimating it per signal would let later patterns leak backwards.

False discoveries. Every cell is tested against the base rate with an exact
binomial test, and Benjamini-Hochberg decides which survive. Consecutive signals
share their outcomes (a 12-bar horizon overlaps the next 11 bars), so the test
uses a de-clustered subset: signals at least one horizon apart. The reported
counts and shrunk rates still use every signal, which is why they run optimistic;
the test is the conservative half.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime
from math import exp, lgamma, log
from typing import Any, Iterable, Mapping, Sequence

from .context import DIMENSIONS, ContextTagger
from .contracts import ContractSpec
from .data import Bar, BarSeries
from .patterns import PATTERN_REGISTRY
from .scanner import completed_bars, scan_series
from .study import DEFAULT_HORIZONS, MIN_OCCURRENCES, _forward, run_pattern_study

METHOD = "walk_forward_v1"
K_DEFAULT = 60.0        # prior strength (pseudo-samples) when it cannot be estimated
K_MIN = 20.0
K_MAX = 2000.0
FDR_Q = 0.10
MIN_TEST_N = 10         # a cell smaller than this is not tested (and not counted in the family)
STORED_SPLIT_MIN = 10   # splits smaller than this are not written to the stored study


# --------------------------------------------------------------------------
# small statistics
# --------------------------------------------------------------------------
def binomial_two_sided_p(wins: int, n: int, p0: float) -> float | None:
    """Exact two-sided binomial test: how often chance gives an outcome this rare or rarer."""

    if n <= 0 or not (0.0 < p0 < 1.0):
        return None
    log_p, log_q, base = log(p0), log(1.0 - p0), lgamma(n + 1)

    def pmf(k: int) -> float:
        return exp(base - lgamma(k + 1) - lgamma(n - k + 1) + k * log_p + (n - k) * log_q)

    observed = pmf(wins)
    total = sum(value for value in (pmf(k) for k in range(n + 1)) if value <= observed * (1 + 1e-9))
    return min(1.0, total)


def beta_shrink(wins: float, n: float, base: float, strength: float) -> float:
    """Posterior mean of a win rate under a Beta prior centred on the base rate."""

    return (wins + strength * base) / (n + strength)


def estimate_prior_strength(cells: Iterable[tuple[int, int, float]]) -> float:
    """Prior strength from the spread of observed edges beyond what sampling noise explains.

    ``cells`` is (wins, n, base_rate). The prior variance of true edges is the
    mean of (edge^2 - sampling variance); a Beta prior with that variance and
    mean at the base rate has strength p(1-p)/variance - 1.
    """

    rows = [(wins / n - base, base * (1 - base) / n, base) for wins, n, base in cells if n >= MIN_TEST_N and 0 < base < 1]
    if len(rows) < 5:
        return K_DEFAULT
    spread = sum(edge * edge - noise for edge, noise, _ in rows) / len(rows)
    if spread <= 0:
        return K_MAX        # no real dispersion across patterns: everything is shrunk hard
    mean_base = sum(base for *_, base in rows) / len(rows)
    return float(min(K_MAX, max(K_MIN, mean_base * (1 - mean_base) / spread - 1)))


def benjamini_hochberg(p_values: Sequence[float | None], q: float = FDR_Q) -> list[bool]:
    """Which hypotheses survive a false-discovery rate of ``q``. ``None`` is never rejected."""

    indexed = sorted((p, i) for i, p in enumerate(p_values) if p is not None)
    m = len(indexed)
    cutoff = 0
    for rank, (p, _i) in enumerate(indexed, start=1):
        if p <= rank / m * q:
            cutoff = rank
    keep = {i for _p, i in indexed[:cutoff]}
    return [i in keep for i in range(len(p_values))]


# --------------------------------------------------------------------------
# cumulative cells: any as-of query is a bisect
# --------------------------------------------------------------------------
@dataclass
class Agg:
    n: int = 0
    wins: int = 0
    ret: float = 0.0
    ret2: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0


class _Cell:
    __slots__ = ("idx", "wins", "ret", "ret2", "mfe", "mae")

    def __init__(self) -> None:
        self.idx: list[int] = []
        self.wins = [0]
        self.ret = [0.0]
        self.ret2 = [0.0]
        self.mfe = [0.0]
        self.mae = [0.0]


class CellIndex:
    """Outcomes bucketed by context cell, with running totals per bucket.

    Entries must arrive in non-decreasing bar order. A query for "everything
    that finished by bar t, in these contexts" is then one bisect per bucket.
    """

    def __init__(self) -> None:
        self._cells: dict[tuple, _Cell] = {}

    def add(self, idx: int, cell: tuple, ret: float, mfe: float = 0.0, mae: float = 0.0) -> None:
        bucket = self._cells.setdefault(cell, _Cell())
        bucket.idx.append(idx)
        bucket.wins.append(bucket.wins[-1] + (1 if ret > 0 else 0))
        bucket.ret.append(bucket.ret[-1] + ret)
        bucket.ret2.append(bucket.ret2[-1] + ret * ret)
        bucket.mfe.append(bucket.mfe[-1] + mfe)
        bucket.mae.append(bucket.mae[-1] + mae)

    def values(self, position: int) -> set[str]:
        return {cell[position] for cell in self._cells}

    def query(self, hi: int, lo: int | None = None, where: Mapping[int, str] | None = None) -> Agg:
        """Entries with ``lo <= bar <= hi`` whose cell matches ``where`` (position -> value)."""

        out = Agg()
        for cell, bucket in self._cells.items():
            if where and any(cell[pos] != value for pos, value in where.items()):
                continue
            end = bisect_right(bucket.idx, hi)
            start = bisect_left(bucket.idx, lo) if lo is not None else 0
            if end <= start:
                continue
            out.n += end - start
            out.wins += bucket.wins[end] - bucket.wins[start]
            out.ret += bucket.ret[end] - bucket.ret[start]
            out.ret2 += bucket.ret2[end] - bucket.ret2[start]
            out.mfe += bucket.mfe[end] - bucket.mfe[start]
            out.mae += bucket.mae[end] - bucket.mae[start]
        return out


def finish(agg: Agg, base: Agg, *, strength: float, min_samples: int = MIN_OCCURRENCES) -> dict[str, Any]:
    """One cell's numbers, raw and shrunk, from running totals."""

    if agg.n == 0:
        return {"count": 0}
    mean = agg.ret / agg.n
    variance = max(0.0, agg.ret2 / agg.n - mean * mean)
    deviation = variance ** 0.5
    row: dict[str, Any] = {
        "count": agg.n,
        "win_rate": round(agg.wins / agg.n, 4),
        "average_return": round(mean, 6),
        "return_std": round(deviation, 6),
        "average_mfe": round(agg.mfe / agg.n, 6),
        "average_mae": round(agg.mae / agg.n, 6),
        "t_stat": round(mean / (deviation / agg.n ** 0.5), 2) if deviation > 0 else None,
        "enough_samples": agg.n >= min_samples,
        "prior_strength": round(strength, 1),
    }
    if base.n:
        base_rate = base.wins / base.n
        base_mean = base.ret / base.n
        shrunk = beta_shrink(agg.wins, agg.n, base_rate, strength)
        row.update(
            base_win_rate=round(base_rate, 4),
            base_average_return=round(base_mean, 6),
            edge_win_rate=round(agg.wins / agg.n - base_rate, 4),
            edge_return=round(mean - base_mean, 6),
            shrunk_win_rate=round(shrunk, 4),
            shrunk_edge_win_rate=round(shrunk - base_rate, 4),
            # the return edge is pulled toward zero by the same n / (n + k) weight
            shrunk_edge_return=round((mean - base_mean) * agg.n / (agg.n + strength), 6),
        )
    return row


def confidence_label(stats: Mapping[str, Any]) -> str:
    """The word the chart shows, judged on the shrunk edge and the false-discovery check."""

    count = int(stats.get("count") or 0)
    if not count:
        return "측정 없음"
    if count < MIN_OCCURRENCES:
        return "표본 부족"
    edge = stats.get("shrunk_edge_win_rate")
    if edge is None or edge <= 0:
        return "기준 미달"
    if stats.get("fdr_significant"):
        return "강함" if abs(float(stats.get("t_stat") or 0)) >= 3 else "보통"
    return "약함"


# --------------------------------------------------------------------------
# the walk-forward engine
# --------------------------------------------------------------------------
@dataclass
class _Event:
    index: int
    cell: tuple
    forward: dict[int, dict[str, float]]


class WalkForward:
    """Every query answers: what had finished by bar ``t``, and what did it say?"""

    def __init__(
        self,
        bars: Sequence[Bar],
        tagger: ContextTagger,
        signals: Sequence[Mapping[str, Any]],
        horizons: Sequence[int],
        *,
        window_bars: int | None = None,
    ):
        self.bars = bars
        self.horizons = tuple(horizons)
        self.window_bars = window_bars
        self.cells = [tagger.tag(index).key() for index in range(len(bars))]
        n = len(bars)
        closes = [bar.close for bar in bars]
        self.base: dict[tuple[int, str], CellIndex] = {}
        for horizon in self.horizons:
            longs, shorts = CellIndex(), CellIndex()
            for i in range(n - horizon):
                entry, exit_price = closes[i], closes[i + horizon]
                if entry <= 0 or exit_price <= 0:
                    continue
                longs.add(i, self.cells[i], exit_price / entry - 1)
                shorts.add(i, self.cells[i], entry / exit_price - 1)
            self.base[(horizon, "bullish")] = longs
            self.base[(horizon, "bearish")] = shorts

        self.events: dict[str, list[_Event]] = {}
        for signal in sorted(signals, key=lambda item: item["index"]):
            long = signal["direction"] == "bullish"
            forward = {}
            for horizon in self.horizons:
                measured = _forward(bars, signal["index"], horizon, long=long)
                if measured:
                    forward[horizon] = measured
            self.events.setdefault(signal["pattern"], []).append(_Event(signal["index"], self.cells[signal["index"]], forward))
        self.index: dict[tuple[str, int], CellIndex] = {}
        for pattern, events in self.events.items():
            for horizon in self.horizons:
                cells = CellIndex()
                for event in events:
                    got = event.forward.get(horizon)
                    if got:
                        cells.add(event.index, event.cell, got["return"], got["mfe"], got["mae"])
                self.index[(pattern, horizon)] = cells

    # -- queries ---------------------------------------------------------
    def _bounds(self, t: int, horizon: int) -> tuple[int, int | None]:
        return t - horizon, (t - self.window_bars if self.window_bars else None)

    def raw(self, pattern: str, direction: str, t: int, horizon: int, where: Mapping[str, str] | None = None) -> tuple[Agg, Agg]:
        """Pattern totals and base totals for outcomes finished by bar ``t``."""

        hi, lo = self._bounds(t, horizon)
        positions = {DIMENSIONS.index(dim): value for dim, value in (where or {}).items()}
        cells = self.index.get((pattern, horizon))
        agg = cells.query(hi, lo, positions) if cells else Agg()
        return agg, self.base[(horizon, direction)].query(hi, lo, positions)

    def record(self, pattern: str, direction: str, t: int, horizon: int, where: Mapping[str, str] | None = None, *, strength: float = K_DEFAULT) -> dict[str, Any]:
        agg, base = self.raw(pattern, direction, t, horizon, where)
        return finish(agg, base, strength=strength)

    def matched(self, pattern: str, direction: str, t: int, horizon: int, context: Mapping[str, Any], *, strength: float = K_DEFAULT) -> dict[str, Any]:
        """The narrowest context with enough samples, found by adding one dimension at a time."""

        where: dict[str, str] = {}
        for dim in DIMENSIONS:
            value = context.get(dim)
            if value in (None, "unknown", "all"):
                continue
            agg, _base = self.raw(pattern, direction, t, horizon, {**where, dim: value})
            if agg.n >= MIN_OCCURRENCES:
                where[dim] = value
        row = self.record(pattern, direction, t, horizon, where or None, strength=strength)
        row["dims"] = list(where)
        return row

    def declustered_wins(self, pattern: str, t: int, horizon: int, where: Mapping[str, str] | None = None) -> tuple[int, int]:
        """(wins, n) over finished signals at least one horizon apart, for an independent-ish test."""

        positions = {DIMENSIONS.index(dim): value for dim, value in (where or {}).items()}
        hi, lo = self._bounds(t, horizon)
        wins = n = 0
        last = None
        for event in self.events.get(pattern, []):
            if event.index > hi or (lo is not None and event.index < lo):
                continue
            if any(event.cell[pos] != value for pos, value in positions.items()):
                continue
            got = event.forward.get(horizon)
            if not got or (last is not None and event.index - last < horizon):
                continue
            last = event.index
            n += 1
            wins += 1 if got["return"] > 0 else 0
        return wins, n


# --------------------------------------------------------------------------
# claims: what the record said at the moment of a signal
# --------------------------------------------------------------------------
def _claim_from(row: Mapping[str, Any], *, basis: str, source: str) -> dict[str, Any]:
    shrunk = row.get("shrunk_win_rate")
    return {
        "count": int(row.get("count") or 0),
        "win_rate": shrunk if shrunk is not None else row.get("win_rate"),
        "raw_win_rate": row.get("win_rate"),
        "base_win_rate": row.get("base_win_rate"),
        "average_mfe": row.get("average_mfe"),
        "average_mae": row.get("average_mae"),
        "basis": basis,
        "source": source,
    }


def walkforward_claim(wf: WalkForward, signal: Mapping[str, Any], t: int) -> dict[str, dict[str, Any]]:
    """The record, per horizon, using only what had finished before bar ``t``."""

    claim = {}
    for horizon in wf.horizons:
        row = wf.matched(signal["pattern"], signal["direction"], t, horizon, signal["context"])
        if int(row.get("count") or 0) >= MIN_OCCURRENCES:
            claim[str(horizon)] = _claim_from(row, basis="+".join(row["dims"]) or "pooled", source="walkforward_asof")
        else:
            claim[str(horizon)] = {"count": int(row.get("count") or 0), "win_rate": None, "basis": "표본 부족", "source": "walkforward_asof"}
    return claim


def pick_record(stats_by_horizon: Mapping[str, Mapping[str, Any]], context: Mapping[str, Any] | None, *, min_samples: int = MIN_OCCURRENCES) -> dict[str, Any] | None:
    """What the chart quotes for one pattern: a horizon, then a context split if it has the samples.

    The horizon is the one with the largest |t| among those with enough samples.
    Picking the best of four horizons would overstate, but the false-discovery
    flag on the cell was computed across every horizon, so a winner that is
    flagged has already paid for the choice.
    """

    best_key, best = None, None
    for key, stats in stats_by_horizon.items():
        if int(stats.get("count") or 0) < min_samples:
            continue
        if best is None or abs(stats.get("t_stat") or 0) > abs(best.get("t_stat") or 0):
            best_key, best = key, stats
    if best is None or best_key is None:
        return None
    chosen, basis = best, "전체"
    best_split = None
    for dim in DIMENSIONS:
        value = (context or {}).get(dim)
        split = ((best.get("context") or {}).get(dim) or {}).get(value) if value else None
        if split and int(split.get("count") or 0) >= min_samples:
            if best_split is None or int(split["count"]) > int(best_split[1]["count"]):
                best_split = (f"{dim}={value}", split)
    if best_split:
        basis, chosen = best_split[0], {**best, **best_split[1]}
    return {"horizon": int(best_key), "stats": dict(chosen), "basis": basis, "pooled": dict(best)}


# --------------------------------------------------------------------------
# the study
# --------------------------------------------------------------------------
def _compact(stats: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "count", "win_rate", "base_win_rate", "shrunk_win_rate", "shrunk_edge_win_rate", "edge_win_rate",
        "average_return", "shrunk_edge_return", "t_stat", "p_value", "fdr_significant", "confidence",
    )
    return {key: stats[key] for key in keys if key in stats}


def run_walkforward_study(
    series: BarSeries,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    patterns: Sequence[str] | None = None,
    min_occurrences: int = MIN_OCCURRENCES,
    contract: ContractSpec | None = None,
    window_bars: int | None = None,
    now: datetime | None = None,
    with_legacy: bool = True,
) -> dict[str, Any]:
    """The study the chart quotes. Same shape as the old one, plus what the old one lacked."""

    horizons = tuple(sorted({int(value) for value in horizons if int(value) > 0}))
    done = completed_bars(series, now=now)
    if len(done) < max(horizons) + 60:
        raise ValueError("not enough bars to measure the longest horizon")
    clean = BarSeries(symbol=series.symbol, interval=series.interval, bars=done)
    tagger = ContextTagger(done, interval=series.interval)
    signals = list(scan_series(clean, patterns=patterns, tagger=tagger, now=now))
    wf = WalkForward(done, tagger, signals, horizons, window_bars=window_bars)
    last = len(done) - 1

    # phase 1: raw totals for every cell, pooled and split by one dimension
    cells: list[dict[str, Any]] = []
    for name, (label, direction, _detector) in PATTERN_REGISTRY.items():
        if patterns and name not in patterns:
            continue
        for horizon in horizons:
            pooled = wf.raw(name, direction, last, horizon)
            cells.append({"pattern": name, "direction": direction, "horizon": horizon, "dim": None, "value": None, "agg": pooled[0], "base": pooled[1]})
            index = wf.index.get((name, horizon))
            if index is None:
                continue
            for position, dim in enumerate(DIMENSIONS):
                for value in sorted(index.values(position)):
                    if value in ("unknown", "all"):
                        continue
                    agg, base = wf.raw(name, direction, last, horizon, {dim: value})
                    if agg.n >= STORED_SPLIT_MIN:
                        cells.append({"pattern": name, "direction": direction, "horizon": horizon, "dim": dim, "value": value, "agg": agg, "base": base})

    # phase 2: one prior strength per (horizon, direction), from the pooled cells
    strengths: dict[tuple[int, str], float] = {}
    for horizon in horizons:
        for direction in ("bullish", "bearish"):
            strengths[(horizon, direction)] = estimate_prior_strength(
                (c["agg"].wins, c["agg"].n, c["base"].wins / c["base"].n)
                for c in cells
                if c["dim"] is None and c["horizon"] == horizon and c["direction"] == direction and c["base"].n and c["agg"].n
            )
    for cell in cells:
        strength = strengths[(cell["horizon"], cell["direction"])]
        cell["stats"] = finish(cell["agg"], cell["base"], strength=strength, min_samples=min_occurrences)
        where = {cell["dim"]: cell["value"]} if cell["dim"] else None
        wins, n = wf.declustered_wins(cell["pattern"], last, cell["horizon"], where)
        cell["stats"]["independent_count"] = n
        cell["p_value"] = None
        if n >= MIN_TEST_N and cell["base"].n:
            p0 = cell["base"].wins / cell["base"].n
            p = binomial_two_sided_p(wins, n, p0)
            cell["p_value"] = p
            cell["stats"]["p_value"] = round(p, 5) if p is not None else None

    # phase 3: one false-discovery family over everything that was tested
    family = [c for c in cells if c["p_value"] is not None]
    for cell, passed in zip(family, benjamini_hochberg([c["p_value"] for c in family])):
        cell["stats"]["fdr_significant"] = bool(passed)
    for cell in cells:
        cell["stats"].setdefault("fdr_significant", False)
        cell["stats"]["confidence"] = confidence_label(cell["stats"])
        if contract is not None and cell["dim"] is None and cell["stats"].get("count"):
            shrunk_mean = (cell["stats"].get("base_average_return") or 0) + (cell["stats"].get("shrunk_edge_return") or 0)
            cell["stats"]["money_per_trade"] = round(
                shrunk_mean * done[-1].close * contract.multiplier
                - contract.commission_per_side * 2
                - contract.typical_slippage_ticks * contract.tick_value * 2,
                2,
            )

    rows: dict[str, dict[str, Any]] = {}
    for name, (label, direction, _detector) in PATTERN_REGISTRY.items():
        if patterns and name not in patterns:
            continue
        rows[name] = {
            "pattern": name,
            "label": label,
            "direction": direction,
            "occurrences": len(wf.events.get(name, [])),
            "horizons": {},
        }
    for cell in cells:
        horizon_row = rows[cell["pattern"]]["horizons"].setdefault(str(cell["horizon"]), {})
        if cell["dim"] is None:
            horizon_row.update(cell["stats"])
        else:
            horizon_row.setdefault("context", {}).setdefault(cell["dim"], {})[cell["value"]] = _compact(cell["stats"])

    ordered = sorted(
        rows.values(),
        key=lambda row: max((h.get("shrunk_edge_return") or 0) for h in row["horizons"].values()) if row["horizons"] else 0,
        reverse=True,
    )
    tested = len(family)
    survivors = sum(1 for c in family if c["stats"].get("fdr_significant") and (c["stats"].get("shrunk_edge_win_rate") or 0) > 0)
    legacy = run_pattern_study(clean, horizons=horizons, patterns=patterns, min_occurrences=min_occurrences, contract=contract) if with_legacy else None
    return {
        "method": METHOD,
        "symbol": series.symbol,
        "interval": series.interval,
        "bars": len(done),
        "start": done[0].timestamp.isoformat(),
        "end": done[-1].timestamp.isoformat(),
        "horizons": list(horizons),
        "window": f"rolling {window_bars} bars" if window_bars else "expanding",
        "signals": len(signals),
        "prior_strength": {f"{h}:{d}": round(v, 1) for (h, d), v in strengths.items()},
        "fdr": {"q": FDR_Q, "tested": tested, "survivors": survivors},
        "base_rate": legacy.as_dict()["base_rate"] if legacy else {},
        "patterns": ordered,
        "legacy_patterns": legacy.as_dict()["patterns"] if legacy else [],
        "notes": [
            "이 통계는 신호가 뜬 시점에 이미 결과가 끝나 있던 과거 신호만으로 계산했습니다(워크포워드, 누적 구간).",
            "승률은 같은 구간 아무 봉의 기준 승률 쪽으로 표본 수에 따라 당겨 보정한 값입니다(수축). 표본이 적을수록 더 많이 당겨집니다.",
            "패턴 수십 개를 동시에 검사하면 우연히 좋아 보이는 칸이 생깁니다. 거짓 발견율(BH, q=0.10) 검사를 통과하지 못하면 '약함' 이하로만 표시합니다.",
            "맥락(세션·추세·변동성·지표 근접)별 기록은 표본이 충분할 때만 쓰고, 모자라면 전체 기록으로 되돌립니다.",
            "연속해서 뜬 신호는 결과가 겹치므로 검정에는 한 구간 이상 떨어진 신호만 씁니다. 표시되는 표본 수는 전부 센 값입니다.",
            f"표본이 {min_occurrences}회 미만이면 통계로 말할 수 없습니다.",
        ],
    }

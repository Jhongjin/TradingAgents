"""Similar past charts: a nearest-neighbour search over shapes.

Research only. Nothing here trades, and the numbers it produces are descriptive
("what followed the most similar looking past windows"), not a forecast. The
walk-forward check in ``validate`` decides how the page may talk about them.

Shape vector (scale free)
-------------------------
For a window of ``W`` bars, take the ``W`` log returns, divide them by the
window's own root-mean-square (so a quiet week and a wild week of the same
shape look the same), and keep the cumulative path of that. The path is then
averaged into ``blocks`` equal blocks (60 bars -> 20 points), which keeps the
shape, drops bar-level noise and makes the matrix small (766k bars x 20).
Distance is the Euclidean distance between two such paths. Similarity is
``max(0, 1 - d / |q|)`` with ``|q|`` the length of the query's shape vector: 1 for an
identical shape, 0 for one no closer than a flat line.

A return across a market break (weekend, holiday: a gap longer than four hours)
is set to zero inside the shape, so a Sunday-open gap is not read as a shape.
The forward paths keep every real price move, gaps included.

No look-ahead
-------------
A candidate window ending at bar ``e`` is allowed only when its whole forward
path (``max(horizons)`` bars) ends before the query window starts:
``e + Hmax < query_start``. The ``K`` analogs are chosen greedily and must be
at least ``min_separation`` bars apart, so they are distinct episodes and not
ten neighbours of one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import lgamma, exp, log, sqrt
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .contracts import CONTRACTS, GOLD_FUTURES
from .data import BarSeries, cache_dir, cache_path

WINDOW = 60
NEIGHBOURS = 10
HORIZONS = (12, 24, 72)
BLOCKS = 20
BREAK_SECONDS = 4 * 3600
BASE_SAMPLES = 20_000
VERSION = 1
LABEL_PREFIX = "gold:analogs"


def analogs_label(symbol: str, interval: str) -> str:
    """The backtest_runs label the page reads (symbol and interval fit in 64 chars)."""

    return f"{LABEL_PREFIX}:{symbol}:{interval}"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Arrays:
    symbol: str
    interval: str
    ts: np.ndarray        # int64 epoch seconds, ascending, unique
    close: np.ndarray     # float64
    volume: np.ndarray    # float64

    def __len__(self) -> int:
        return int(self.ts.shape[0])


def arrays_from_series(series: BarSeries) -> Arrays:
    bars = sorted(series.bars, key=lambda bar: bar.timestamp)
    return Arrays(
        symbol=series.symbol,
        interval=series.interval,
        ts=np.array([int(bar.timestamp.timestamp()) for bar in bars], dtype=np.int64),
        close=np.array([bar.close for bar in bars], dtype=np.float64),
        volume=np.array([bar.volume for bar in bars], dtype=np.float64),
    )


def load_arrays(symbol: str, interval: str) -> Arrays:
    """The file store's history for one series, read straight into numpy."""

    import pandas as pd

    path = cache_path(symbol, interval)
    if not path.exists():
        raise FileNotFoundError(f"no stored bars at {path}; run `bars sync` or set GOLDLAB_CACHE_DIR")
    frame = pd.read_csv(path, usecols=["timestamp", "close", "volume"])
    stamps = pd.to_datetime(frame["timestamp"], utc=True, format="ISO8601")
    seconds = (stamps.astype("int64") // (10**9 if stamps.dt.unit == "ns" else {"us": 10**6, "ms": 10**3, "s": 1}[stamps.dt.unit])).to_numpy(dtype=np.int64)
    close = frame["close"].to_numpy(dtype=np.float64)
    volume = frame["volume"].fillna(0.0).to_numpy(dtype=np.float64)
    order = np.argsort(seconds, kind="stable")
    seconds, close, volume = seconds[order], close[order], volume[order]
    keep = np.ones(seconds.shape[0], dtype=bool)
    keep[1:] = seconds[1:] != seconds[:-1]
    keep &= np.isfinite(close) & (close > 0)
    return Arrays(symbol=symbol, interval=interval, ts=seconds[keep], close=close[keep], volume=volume[keep])


# ---------------------------------------------------------------------------
# shape features
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Features:
    window: int
    blocks: int
    matrix: np.ndarray    # (n, blocks) float32; row e describes the window ending at bar e
    rms: np.ndarray       # (n,) float64 root-mean-square of the window's returns
    valid: np.ndarray     # (n,) bool
    norm: np.ndarray      # (n,) float64 length of each shape vector


def _returns(close: np.ndarray, ts: np.ndarray) -> np.ndarray:
    r = np.zeros(close.shape[0], dtype=np.float64)
    if close.shape[0] > 1:
        r[1:] = np.diff(np.log(close))
        r[1:][np.diff(ts) > BREAK_SECONDS] = 0.0
    return r


def build_features(arrays: Arrays, *, window: int = WINDOW, blocks: int = BLOCKS) -> Features:
    if window % blocks:
        raise ValueError("window must be a multiple of blocks")
    n = len(arrays)
    size = window // blocks
    r = _returns(arrays.close, arrays.ts)
    C = np.cumsum(r)
    CC = np.cumsum(C)
    sq = np.cumsum(r * r)
    matrix = np.zeros((n, blocks), dtype=np.float32)
    rms = np.zeros(n, dtype=np.float64)
    valid = np.zeros(n, dtype=bool)
    if n > window:
        e = np.arange(window, n)
        a = e - window
        rms_e = np.sqrt((sq[e] - sq[a]) / window)
        ok = rms_e > 1e-12
        safe = np.where(ok, rms_e, 1.0)
        for k in range(blocks):
            block_mean = (CC[a + (k + 1) * size] - CC[a + k * size]) / size
            matrix[e, k] = ((block_mean - C[a]) / safe).astype(np.float32)
        rms[e] = rms_e
        valid[e] = ok
    matrix[~valid] = 0.0
    norm = np.sqrt((matrix.astype(np.float64) ** 2).sum(axis=1))
    return Features(window=window, blocks=blocks, matrix=matrix, rms=rms, valid=valid, norm=norm)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def search(
    feats: Features,
    query_end: int,
    *,
    k: int = NEIGHBOURS,
    max_horizon: int = max(HORIZONS),
    min_separation: int | None = None,
) -> list[tuple[int, float]]:
    """The ``k`` most similar past windows as (end index, distance), best first.

    Only windows whose forward path of ``max_horizon`` bars ends before the query
    window starts are candidates (no look-ahead, no overlap with the query).
    """

    window = feats.window
    sep = 2 * window if min_separation is None else int(min_separation)
    hi = query_end - window - max_horizon - 1          # last allowed candidate end
    if hi < window or not feats.valid[query_end]:
        return []
    q = feats.matrix[query_end]
    block = feats.matrix[window : hi + 1]
    qq = float(np.dot(q, q))
    d2 = (feats.norm[window : hi + 1] ** 2).astype(np.float32) + np.float32(qq) - np.float32(2.0) * (block @ q)
    d = np.sqrt(np.maximum(d2, 0.0), dtype=np.float32).astype(np.float64)
    d[~feats.valid[window : hi + 1]] = np.inf
    chosen: list[tuple[int, float]] = []
    for _ in range(k):
        j = int(np.argmin(d))
        if not np.isfinite(d[j]):
            break
        end = j + window
        exact = float(np.linalg.norm(feats.matrix[end].astype(np.float64) - q.astype(np.float64)))
        chosen.append((end, exact))
        d[max(0, j - sep + 1) : j + sep] = np.inf       # distinct episodes
    chosen.sort(key=lambda item: (item[1], item[0]))
    return chosen


def similarity(distance: float, query_norm: float) -> float:
    """1 for an identical shape, 0 when the candidate is no closer than a flat line is."""

    return max(0.0, 1.0 - distance / query_norm) if query_norm > 0 else 0.0


def _forward(close: np.ndarray, end: int, horizon: int) -> np.ndarray:
    """Returns from the close at ``end`` for 0..horizon bars ahead."""

    return close[end : end + horizon + 1] / close[end] - 1.0


def _iqr(values: np.ndarray) -> tuple[float, float, float]:
    q25, q50, q75 = np.percentile(values, [25, 50, 75])
    return float(q25), float(q50), float(q75)


def _base_rates(arrays: Arrays, feats: Features, query_end: int, horizons: Sequence[int]) -> dict[int, dict[str, float]]:
    """What happens after any past window of the same instrument, in the query's own volatility."""

    window, hmax = feats.window, max(horizons)
    hi = query_end - window - hmax - 1
    idx = np.arange(window, hi + 1) if hi >= window else np.array([], dtype=int)
    idx = idx[feats.valid[idx]] if idx.size else idx
    if idx.size > BASE_SAMPLES:
        idx = idx[np.linspace(0, idx.size - 1, BASE_SAMPLES).astype(int)]
    out: dict[int, dict[str, float]] = {}
    if not idx.size:
        return out
    scale = feats.rms[query_end] / feats.rms[idx]
    for h in horizons:
        fwd = arrays.close[idx + h] / arrays.close[idx] - 1.0
        moved = fwd != 0
        q25, q50, q75 = _iqr(fwd[moved] * scale[moved]) if moved.any() else (0.0, 0.0, 0.0)
        out[h] = {
            "share_up": float((fwd[moved] > 0).mean()) if moved.any() else 0.5,
            "median": q50, "q25": q25, "q75": q75, "samples": int(idx.size),
        }
    return out


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc).isoformat()


def current_analogs(
    arrays: Arrays,
    *,
    window: int = WINDOW,
    k: int = NEIGHBOURS,
    horizons: Sequence[int] = HORIZONS,
    feats: Features | None = None,
    min_separation: int | None = None,
    query_end: int | None = None,
) -> dict[str, Any]:
    """The analog report for the newest window (or for ``query_end``, used by the tests)."""

    horizons = tuple(horizons)
    hmax = max(horizons)
    feats = feats or build_features(arrays, window=window)
    q = len(arrays) - 1 if query_end is None else int(query_end)
    found = search(feats, q, k=k, max_horizon=hmax, min_separation=min_separation)
    close = arrays.close
    items: list[dict[str, Any]] = []
    scaled: list[np.ndarray] = []
    raw_forward: list[np.ndarray] = []
    for end, distance in found:
        ratio = feats.rms[q] / feats.rms[end]
        fwd = _forward(close, end, hmax)
        raw_forward.append(fwd)
        scaled.append(fwd * ratio)
        items.append(
            {
                "start": _iso(arrays.ts[end - window]),
                "end": _iso(arrays.ts[end]),
                "similarity": round(similarity(distance, float(feats.norm[q])), 4),
                "distance": round(distance, 4),
                "vol_ratio": round(float(ratio), 3),
                "end_index": int(end),
                "forward": [round(float(x), 5) for x in scaled[-1]],
            }
        )
    base = _base_rates(arrays, feats, q, horizons)
    summary: dict[str, Any] = {}
    for h in horizons:
        if not found:
            break
        raw = np.array([f[h] for f in raw_forward])
        sc = np.array([f[h] for f in scaled])
        up = int((raw > 0).sum())
        down = int((raw < 0).sum())
        q25, q50, q75 = _iqr(sc)
        b = base.get(h) or {}
        summary[str(h)] = {
            "n": len(found), "up": up, "down": down,
            "share_up": round(up / max(1, up + down), 4),
            "median": round(q50, 5), "q25": round(q25, 5), "q75": round(q75, 5),
            "base_share_up": round(b.get("share_up", float("nan")), 4) if b else None,
            "base_median": round(b.get("median", 0.0), 5) if b else None,
            "base_q25": round(b.get("q25", 0.0), 5) if b else None,
            "base_q75": round(b.get("q75", 0.0), 5) if b else None,
        }
    path_len = min(window, q)
    query_path = close[q - path_len : q + 1] / close[q] - 1.0
    median_path = np.median(np.array(scaled), axis=0) if scaled else np.array([])
    return {
        "version": VERSION,
        "symbol": arrays.symbol,
        "interval": arrays.interval,
        "window": window,
        "k": k,
        "horizons": list(horizons),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "last_bar": _iso(arrays.ts[q]),
        "query_close": float(close[q]),
        "history": {"bars": int(q + 1), "first": _iso(arrays.ts[0]), "last": _iso(arrays.ts[q])},
        "method": "log-return path / window RMS, 20-block means, Euclidean; forward paths rescaled to the query's volatility",
        "analogs": items,
        "summary": summary,
        "median_path": [round(float(x), 5) for x in median_path],
        "query_path": [round(float(x), 5) for x in query_path],
    }


# ---------------------------------------------------------------------------
# walk-forward validation: does "look like the past" predict direction?
# ---------------------------------------------------------------------------
def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def binom_two_sided(wins: int, n: int, p0: float) -> float | None:
    """Exact two-sided binomial p-value (same rule as ``walkforward.binomial_two_sided_p``)."""

    if n <= 0 or not (0.0 < p0 < 1.0):
        return None
    log_p, log_q, base = log(p0), log(1.0 - p0), lgamma(n + 1)

    def pmf(i: int) -> float:
        return exp(base - lgamma(i + 1) - lgamma(n - i + 1) + i * log_p + (n - i) * log_q)

    observed = pmf(wins)
    return min(1.0, sum(v for v in (pmf(i) for i in range(n + 1)) if v <= observed * (1 + 1e-9)))


def _mean_ci(values: np.ndarray) -> dict[str, float]:
    n = values.size
    if n == 0:
        return {"n": 0, "mean": 0.0, "ci_low": 0.0, "ci_high": 0.0, "total": 0.0}
    mean = float(values.mean())
    se = float(values.std(ddof=1) / sqrt(n)) if n > 1 else 0.0
    return {"n": int(n), "mean": round(mean, 2), "ci_low": round(mean - 1.96 * se, 2), "ci_high": round(mean + 1.96 * se, 2), "total": round(float(values.sum()), 2)}


def _score(pred_up: np.ndarray, agree: np.ndarray, entry: np.ndarray, exit_: np.ndarray, spec) -> dict[str, Any]:
    """Hit rate and money for one set of predictions. ``agree`` is how many analogs share the call."""

    n = int(pred_up.size)
    outcome_up = exit_ > entry
    hit = pred_up == outcome_up
    wins = int(hit.sum())
    base_up = float(outcome_up.mean()) if n else 0.5
    majority = max(base_up, 1 - base_up)
    lo, hi = wilson(wins, n)
    pnl = np.array([spec.pnl(float(a), float(b), long=bool(p)) for a, b, p in zip(entry, exit_, pred_up)])
    always_long = np.array([spec.pnl(float(a), float(b), long=True) for a, b in zip(entry, exit_)])
    gross = np.array([(float(b) - float(a)) * spec.multiplier * (1 if p else -1) for a, b, p in zip(entry, exit_, pred_up)])
    return {
        "n": n,
        "hits": wins,
        "hit_rate": round(wins / n, 4) if n else None,
        "hit_ci95": [round(lo, 4), round(hi, 4)],
        "base_up_rate": round(base_up, 4),
        "always_majority_rate": round(majority, 4),
        "edge_over_majority": round(wins / n - majority, 4) if n else None,
        "p_vs_coin": binom_two_sided(wins, n, 0.5),
        "p_vs_majority": binom_two_sided(wins, n, min(max(majority, 1e-6), 1 - 1e-6)),
        "money_per_trade_after_costs": _mean_ci(pnl),
        "money_per_trade_before_costs": _mean_ci(gross),
        "always_long_per_trade_after_costs": _mean_ci(always_long),
    }


def validate(
    arrays: Arrays,
    *,
    window: int = WINDOW,
    k: int = NEIGHBOURS,
    horizons: Sequence[int] = HORIZONS,
    queries: int = 3000,
    burn_fraction: float = 0.2,
    strong_agreement: int = 8,
    progress: Any = None,
) -> dict[str, Any]:
    """Replay history: at each query time use only earlier bars, call a direction, then score it.

    Queries are spread evenly after a burn-in (so the first ones still have years
    of past to search) and spaced at least ``horizon`` bars apart, which makes the
    scored outcomes of one horizon non-overlapping. A horizon whose spacing
    leaves fewer than ``queries`` samples reports how many it really had.
    """

    horizons = tuple(horizons)
    hmax = max(horizons)
    feats = build_features(arrays, window=window)
    spec = CONTRACTS.get(arrays.symbol, GOLD_FUTURES)
    n = len(arrays)
    first = max(int(n * burn_fraction), window + hmax + 2 * window + 10)
    results: dict[str, Any] = {}
    for h in horizons:
        last = n - 1 - h
        span = last - first
        spacing = max(h, int(np.ceil(span / queries)))
        qs = np.arange(first, last + 1, spacing)
        qs = qs[feats.valid[qs]]
        preds, agrees, entries, exits, ups_counts = [], [], [], [], []
        for number, q in enumerate(qs):
            found = search(feats, int(q), k=k, max_horizon=hmax)
            if len(found) < k:
                continue
            ends = np.array([e for e, _ in found])
            fwd = arrays.close[ends + h] / arrays.close[ends] - 1.0
            ups = int((fwd > 0).sum())
            downs = int((fwd < 0).sum())
            med = float(np.median(fwd * (feats.rms[q] / feats.rms[ends])))
            if med == 0:
                continue
            entry, exit_ = float(arrays.close[q]), float(arrays.close[q + h])
            if exit_ == entry:
                continue
            preds.append(med > 0)
            agrees.append(max(ups, downs))
            ups_counts.append(ups)
            entries.append(entry)
            exits.append(exit_)
            if progress and number % 500 == 0:
                progress(f"{arrays.symbol} {arrays.interval} H={h}: {number}/{len(qs)}")
        pred = np.array(preds, dtype=bool)
        agree = np.array(agrees)
        entry, exit_ = np.array(entries), np.array(exits)
        block: dict[str, Any] = {
            "horizon": h,
            "spacing_bars": int(spacing),
            "queries_requested": int(queries),
            "queries_scored": int(pred.size),
            "all": _score(pred, agree, entry, exit_, spec) if pred.size else None,
            "by_agreement": {},
        }
        strong = agree >= strong_agreement
        block["strong"] = _score(pred[strong], agree[strong], entry[strong], exit_[strong], spec) if strong.any() else None
        block["strong_threshold"] = strong_agreement
        for level in range(max(6, k // 2 + 1), k + 1):
            sel = agree == level
            if sel.any():
                s = _score(pred[sel], agree[sel], entry[sel], exit_[sel], spec)
                block["by_agreement"][str(level)] = {x: s[x] for x in ("n", "hits", "hit_rate", "hit_ci95", "base_up_rate", "always_majority_rate")}
        results[str(h)] = block
    verdict = verdict_for(results)
    return {
        "version": VERSION,
        "kind": "research_not_trading_performance",
        "symbol": arrays.symbol,
        "interval": arrays.interval,
        "window": window,
        "k": k,
        "bars": n,
        "first": _iso(arrays.ts[0]),
        "last": _iso(arrays.ts[-1]),
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "contract": spec.symbol,
        "costs": {"slippage_ticks_per_side": spec.typical_slippage_ticks, "commission_per_side": spec.commission_per_side, "contracts": 1},
        "bonferroni_alpha": round(0.05 / len(horizons), 5),
        "horizons": results,
        **verdict,
    }


def verdict_for(results: Mapping[str, Any]) -> dict[str, Any]:
    """Beats the base only if some horizon's hit rate is above the always-majority rate and survives a correction."""

    alpha = 0.05 / max(1, len(results))
    passing = []
    for h, block in results.items():
        all_ = block.get("all")
        if not all_ or all_["p_vs_majority"] is None:
            continue
        if all_["edge_over_majority"] > 0 and all_["p_vs_majority"] < alpha:
            passing.append(int(h))
    if passing:
        return {"beats_base": True, "passing_horizons": passing, "line": f"검증: 10년 순차 검증에서 {', '.join(str(h) for h in passing)}봉 뒤 방향이 기준보다 높았습니다 (연구 결과이며 예측이 아닙니다)"}
    return {"beats_base": False, "passing_horizons": [], "line": "검증: 10년 순차 검증에서 기준보다 낫지 않음 (예측 도구가 아닙니다)"}


def compact_validation(full: Mapping[str, Any]) -> dict[str, Any]:
    """The few numbers the card shows."""

    rows = {}
    for h, block in (full.get("horizons") or {}).items():
        a = block.get("all") or {}
        s = block.get("strong") or {}
        rows[h] = {
            "n": a.get("n"), "hit_rate": a.get("hit_rate"), "hit_ci95": a.get("hit_ci95"),
            "base": a.get("always_majority_rate"), "p_vs_majority": a.get("p_vs_majority"),
            "strong_n": s.get("n"), "strong_hit_rate": s.get("hit_rate"), "strong_base": s.get("always_majority_rate"),
            "money": (a.get("money_per_trade_after_costs") or {}).get("mean"),
        }
    return {
        "beats_base": full.get("beats_base"), "line": full.get("line"), "ran_at": full.get("ran_at"),
        "first": full.get("first"), "last": full.get("last"), "horizons": rows,
    }


# ---------------------------------------------------------------------------
# storage and serving
# ---------------------------------------------------------------------------
def analog_dir() -> Path:
    path = cache_dir() / "analogs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def validation_path(symbol: str, interval: str) -> Path:
    return analog_dir() / f"validation_{symbol.replace('=', '_')}__{interval}.json"


def load_validation(symbol: str, interval: str) -> dict[str, Any] | None:
    path = validation_path(symbol, interval)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def refresh(symbol: str, interval: str, *, repo: Any = None, arrays: Arrays | None = None) -> dict[str, Any]:
    """Compute today's analogs from the file store and, with a repository, store them for the page."""

    arrays = arrays or load_arrays(symbol, interval)
    payload = current_analogs(arrays)
    full = load_validation(symbol, interval)
    if full:
        payload["validation"] = compact_validation(full)
    if repo is not None:
        store_analogs(repo, payload)
    return payload


def store_analogs(repo: Any, payload: Mapping[str, Any]) -> str:
    """One row per (symbol, interval), replaced in place: this is a cache, not a history."""

    day = lambda text: str(text or "")[:10] or "1970-01-01"
    history = payload.get("history") or {}
    return repo.save_backtest_run(
        {
            "start_date": day(history.get("first")),
            "end_date": day(history.get("last")),
            "universe_size": int(history.get("bars") or 0),
            "metrics": {"analogs": dict(payload), "trade_count": 0},
            "config": {"symbol": payload.get("symbol"), "interval": payload.get("interval"), "window": payload.get("window"), "k": payload.get("k")},
            "equity_curve": [],
            "trades": [],
            "notes": ["research only: similar past charts, not a forecast"],
        },
        label=analogs_label(str(payload.get("symbol")), str(payload.get("interval"))),
        keep_latest=True,
    )


def load_stored_analogs(repo: Any, symbol: str, interval: str) -> dict[str, Any] | None:
    """What the lab stored last, or None (the card keeps its placeholder)."""

    if repo is None:
        return None
    try:
        row = repo.latest_backtest_run(label=analogs_label(symbol, interval))
    except Exception:
        return None
    if not row:
        return None
    payload = (row.get("metrics_json") or {}).get("analogs")
    return dict(payload) if isinstance(payload, Mapping) else None

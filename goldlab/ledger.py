"""The signal ledger: what the lab said, and what happened next ("복기").

A study says how a pattern did over history. A ledger asks the harder question:
when the lab recorded a signal on a bar, with only that bar's past in hand, what
did it claim, and what did the market then do?

Each signal is written once, keyed by (symbol, interval, pattern, bar), with its
context tags and the claim in force at that moment. Grades are filled in as
bars arrive, at 4, 12, 24 and 72 bars, and are never rewritten: a grade that
exists is final, so rerunning any command is safe and past records can not drift.

Two kinds of rows share the ledger and are kept apart by ``origin``:

* ``live``: scanned shortly after the bar closed. The claim is the stored study
  that was in force (``claim.source == "stored_study"``).
* ``backfill``: scanned later over stored history. Still point-in-time (the
  scanner never shows a detector a later bar), and the claim is the
  walk-forward record as of that bar. It is a reconstruction, not a diary.

These are research records of a pattern's behaviour. They are not trading
results: there are no fills, fees or position sizes here.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .context import DIMENSIONS, ContextTagger
from .data import BarSeries, cache_dir
from .scanner import completed_bars, scan_series
from .study import DEFAULT_HORIZONS, MIN_OCCURRENCES, _forward
from .walkforward import WalkForward, pick_record, walkforward_claim, _claim_from

STOP_TARGET_ATR = 1.0   # one ATR(14) share of price, scaled by sqrt(horizon), each side


# --------------------------------------------------------------------------
# stores
# --------------------------------------------------------------------------
class FileLedger:
    """One JSON file per (symbol, interval) beside the bar cache."""

    def __init__(self, symbol: str, interval: str, path: Path | None = None):
        safe = symbol.replace("=", "_").replace("/", "_")
        self.path = path or (cache_dir().parent / "ledger" / f"{safe}__{interval}.json")
        self.symbol, self.interval = symbol, interval

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return {item["id"]: item for item in json.loads(self.path.read_text(encoding="utf-8")).get("signals", [])}
        except (OSError, ValueError):
            return {}

    def _write(self, rows: Mapping[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"symbol": self.symbol, "interval": self.interval, "signals": sorted(rows.values(), key=lambda r: (r["ts"], r["id"]))}, ensure_ascii=False)
        handle, temp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(body)
        os.replace(temp, self.path)

    def all(self) -> list[dict[str, Any]]:
        return sorted(self._read().values(), key=lambda r: (r["ts"], r["id"]))

    def pending(self) -> list[dict[str, Any]]:
        return [row for row in self.all() if not row.get("complete")]

    def add(self, signals: Sequence[Mapping[str, Any]]) -> int:
        rows = self._read()
        fresh = [dict(item) for item in signals if item["id"] not in rows]
        for item in fresh:
            rows[item["id"]] = item
        if fresh:
            self._write(rows)
        return len(fresh)

    def update(self, signals: Sequence[Mapping[str, Any]]) -> int:
        rows = self._read()
        for item in signals:
            rows[item["id"]] = dict(item)
        if signals:
            self._write(rows)
        return len(signals)


class DbLedger:
    """The same interface over ``StorageRepository`` (goldlab_signals)."""

    def __init__(self, repo: Any, symbol: str, interval: str):
        self.repo, self.symbol, self.interval = repo, symbol, interval

    def all(self) -> list[dict[str, Any]]:
        return self.repo.goldlab_load_signals(self.symbol, self.interval)

    def pending(self) -> list[dict[str, Any]]:
        return self.repo.goldlab_load_signals(self.symbol, self.interval, pending_only=True)

    def add(self, signals: Sequence[Mapping[str, Any]]) -> int:
        return self.repo.goldlab_add_signals(list(signals))

    def update(self, signals: Sequence[Mapping[str, Any]]) -> int:
        return self.repo.goldlab_update_signals(list(signals))


def open_ledger(symbol: str, interval: str, *, repo: Any = None):
    return DbLedger(repo, symbol, interval) if repo is not None else FileLedger(symbol, interval)


# --------------------------------------------------------------------------
# scanning into the ledger
# --------------------------------------------------------------------------
def _strip(signal: Mapping[str, Any], *, origin: str, claim: Mapping[str, Any] | None, claim_source: str, recorded_at: str) -> dict[str, Any]:
    row = {key: value for key, value in signal.items() if key != "index"}
    row.update(origin=origin, claim=dict(claim or {}), claim_source=claim_source, grades={}, complete=False, recorded_at=recorded_at)
    return row


def scan_into_ledger(
    series: BarSeries,
    store: Any,
    *,
    last_bars: int | None = None,
    study: Mapping[str, Any] | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scan completed bars point-in-time and add the signals the ledger has not seen.

    ``last_bars`` set: a live pass, claims quoted from the stored ``study``. Unset: a
    backfill over everything stored, claims computed walk-forward as of each bar.
    """

    done = completed_bars(series, now=now)
    clean = BarSeries(symbol=series.symbol, interval=series.interval, bars=done)
    tagger = ContextTagger(done, interval=series.interval)
    # a backfill needs every signal in order to know what had finished before each one
    signals = list(scan_series(clean, last_bars=None if last_bars is None else last_bars, tagger=tagger, now=now))
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    origin = "backfill" if last_bars is None else "live"

    if origin == "backfill":
        wf = WalkForward(done, tagger, signals, horizons)
        rows = [_strip(s, origin=origin, claim=walkforward_claim(wf, s, s["index"]), claim_source="walkforward_asof", recorded_at=stamp) for s in signals]
    else:
        rows = []
        saved = (study or {}).get("saved_at")
        for s in signals:
            claim = study_claim(study, s, horizons) if study else {}
            source = "stored_study" if claim else "none"
            row = _strip(s, origin=origin, claim=claim, claim_source=source, recorded_at=stamp)
            if saved:
                row["claim_saved_at"] = saved
            rows.append(row)
    added = store.add(rows)
    return {"scanned_bars": len(done) if last_bars is None else min(last_bars, len(done)), "found": len(rows), "added": added, "origin": origin}


def study_claim(study: Mapping[str, Any] | None, signal: Mapping[str, Any], horizons: Sequence[int]) -> dict[str, dict[str, Any]]:
    """The stored study's record for this pattern in this context, per horizon."""

    row = next((item for item in (study or {}).get("patterns") or [] if item.get("pattern") == signal["pattern"]), None)
    if not row:
        return {}
    walk = (study or {}).get("method") == "walk_forward_v1"
    claim: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        one = {str(horizon): (row.get("horizons") or {}).get(str(horizon)) or {}}
        picked = pick_record(one, signal["context"] if walk else None)
        if picked:
            claim[str(horizon)] = _claim_from(picked["stats"], basis=picked["basis"], source="stored_study" if walk else "stored_study_legacy")
        else:
            stats = one[str(horizon)]
            claim[str(horizon)] = {"count": int(stats.get("count") or 0), "win_rate": None, "basis": "표본 부족", "source": "stored_study"}
    return claim


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------
def _first_touch(bars: Sequence[Any], t: int, horizon: int, entry: float, unit: float, *, long: bool) -> str:
    """Which came first inside the horizon: a +unit target or a -unit stop. A tie goes to the stop."""

    target = entry * (1 + unit) if long else entry * (1 - unit)
    stop = entry * (1 - unit) if long else entry * (1 + unit)
    for bar in bars[t + 1 : t + 1 + horizon]:
        hit_stop = bar.low <= stop if long else bar.high >= stop
        hit_target = bar.high >= target if long else bar.low <= target
        if hit_stop:
            return "stop"
        if hit_target:
            return "target"
    return "none"


def grade_signals(series: BarSeries, signals: Sequence[dict[str, Any]], *, horizons: Sequence[int] = DEFAULT_HORIZONS, now: datetime | None = None) -> list[dict[str, Any]]:
    """Fill in missing grades for signals whose horizon has finished. Returns the changed rows.

    A horizon already graded is skipped, so the result of a rerun is empty.
    """

    done = completed_bars(series, now=now)
    position = {bar.timestamp.astimezone(timezone.utc).isoformat(): i for i, bar in enumerate(done)}
    changed = []
    for signal in signals:
        t = position.get(datetime.fromisoformat(signal["ts"]).astimezone(timezone.utc).isoformat())
        if t is None:
            continue
        long = signal["direction"] == "bullish"
        grades = signal.setdefault("grades", {})
        touched = False
        for horizon in horizons:
            key = str(horizon)
            if key in grades or t + horizon > len(done) - 1:
                continue
            measured = _forward(done, t, horizon, long=long)
            if not measured:
                continue
            atr = (signal.get("context") or {}).get("atr_pct")
            unit = round(atr * STOP_TARGET_ATR * sqrt(horizon), 6) if atr else None
            grades[key] = {
                "return": round(measured["return"], 6),
                "hit": measured["return"] > 0,
                "mfe": round(measured["mfe"], 6),
                "mae": round(measured["mae"], 6),
                "exit": done[t + horizon].close,
                "resolved_at": done[t + horizon].timestamp.astimezone(timezone.utc).isoformat(),
                "stop_target_unit": unit,
                "first_touch": _first_touch(done, t, horizon, done[t].close, unit, long=long) if unit else None,
            }
            touched = True
        complete = all(str(h) in grades for h in horizons)
        if touched or complete != bool(signal.get("complete")):
            signal["complete"] = complete
            changed.append(signal)
    return changed


def grade_ledger(series: BarSeries, store: Any, *, horizons: Sequence[int] = DEFAULT_HORIZONS, now: datetime | None = None) -> dict[str, int]:
    pending = store.pending()
    changed = grade_signals(series, pending, horizons=horizons, now=now)
    store.update(changed)
    return {"pending": len(pending), "graded": len(changed)}


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def _bucket(signals: Iterable[Mapping[str, Any]], horizon: int) -> dict[str, Any]:
    graded = [s for s in signals if str(horizon) in (s.get("grades") or {})]
    n = len(graded)
    if not n:
        return {"n": 0}
    hits = sum(1 for s in graded if s["grades"][str(horizon)]["hit"])
    claimed = [(s["claim"][str(horizon)], s) for s in graded if (s.get("claim") or {}).get(str(horizon), {}).get("win_rate") is not None]
    row: dict[str, Any] = {
        "n": n,
        "hits": hits,
        "hit_rate": round(hits / n, 4),
        "hit_rate_ci": wilson(hits, n),
        "mean_return": round(sum(s["grades"][str(horizon)]["return"] for s in graded) / n, 6),
        "mean_mfe": round(sum(s["grades"][str(horizon)]["mfe"] for s in graded) / n, 6),
        "mean_mae": round(sum(s["grades"][str(horizon)]["mae"] for s in graded) / n, 6),
    }
    touches = [s["grades"][str(horizon)].get("first_touch") for s in graded]
    resolved = [t for t in touches if t]
    if resolved:
        row["target_first"] = round(resolved.count("target") / len(resolved), 4)
        row["stop_first"] = round(resolved.count("stop") / len(resolved), 4)
    if claimed:
        claimed_hits = sum(1 for _c, s in claimed if s["grades"][str(horizon)]["hit"])
        mean_claim = sum(c["win_rate"] for c, _s in claimed) / len(claimed)
        row.update(
            n_claimed=len(claimed),
            claimed_win_rate=round(mean_claim, 4),
            realised_on_claimed=round(claimed_hits / len(claimed), 4),
            calibration_gap=round(claimed_hits / len(claimed) - mean_claim, 4),
        )
    return row


def build_report(signals: Sequence[Mapping[str, Any]], *, horizons: Sequence[int] = DEFAULT_HORIZONS, min_samples: int = MIN_OCCURRENCES) -> dict[str, Any]:
    """Live record against the claim, per pattern and per context. Counts first; rates second."""

    report: dict[str, Any] = {"signals": len(signals), "horizons": list(horizons), "overall": {}, "by_pattern": {}, "by_context": {}, "calibration": {}}
    origins = defaultdict(int)
    for s in signals:
        origins[s.get("origin", "?")] += 1
    report["origins"] = dict(origins)
    for horizon in horizons:
        key = str(horizon)
        report["overall"][key] = _bucket(signals, horizon)
        by_pattern = defaultdict(list)
        by_context = defaultdict(list)
        for s in signals:
            by_pattern[s["pattern"]].append(s)
            for dim in DIMENSIONS:
                by_context[f"{dim}={(s.get('context') or {}).get(dim)}"].append(s)
        for name, group in by_pattern.items():
            report["by_pattern"].setdefault(name, {})[key] = _bucket(group, horizon)
        for name, group in by_context.items():
            report["by_context"].setdefault(name, {})[key] = _bucket(group, horizon)
        # reliability: do signals that claimed more actually win more?
        bins = [(0.0, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 1.01)]
        rows = []
        for low, high in bins:
            group = [s for s in signals if str(horizon) in (s.get("grades") or {}) and low <= ((s.get("claim") or {}).get(key, {}).get("win_rate") or -1) < high]
            if group:
                bucket = _bucket(group, horizon)
                rows.append({"claimed_from": low, "claimed_to": min(high, 1.0), "n": bucket["n"], "claimed": bucket.get("claimed_win_rate"), "realised": bucket["hit_rate"]})
        report["calibration"][key] = rows
    report["min_samples"] = min_samples
    report["notes"] = [
        "연구 기록입니다. 체결·수수료·포지션 크기가 없으므로 거래 성과가 아닙니다.",
        "hit는 진입 봉 종가 기준 방향 수익률이 0보다 큰 경우입니다. 겹치는 신호가 많아 표본 수보다 독립 정보는 적습니다.",
        "claim은 신호가 뜬 시점에 쓸 수 있던 기록(저장된 연구 또는 워크포워드)입니다. 'backfill' 행은 소급 재현이고 'live' 행만 실제로 그때 기록한 것입니다.",
        f"표본 {min_samples}개 미만 칸은 비율을 믿지 마십시오.",
    ]
    return report


def ledger_summary(signals: Sequence[Mapping[str, Any]], *, horizon: int = 12, days: int = 30, now: datetime | None = None) -> dict[str, Any] | None:
    """The one line the chart shows. Live rows if any have been graded, else the backfill, labelled."""

    clock = now or datetime.now(timezone.utc)
    since = clock - timedelta(days=days)
    recent = [s for s in signals if datetime.fromisoformat(s["ts"]) >= since]
    for origin in ("live", "backfill"):
        group = [s for s in recent if s.get("origin") == origin]
        bucket = _bucket(group, horizon)
        if bucket["n"]:
            return {"origin": origin, "horizon": horizon, "days": days, "n": bucket["n"], "hit_rate": bucket["hit_rate"], "claimed_win_rate": bucket.get("claimed_win_rate"), "n_claimed": bucket.get("n_claimed", 0)}
    return None


def ledger_line(summary: Mapping[str, Any] | None) -> str | None:
    if not summary:
        return None
    label = "실시간 기록" if summary["origin"] == "live" else "소급 재현(과거 봉을 당시 정보만으로 다시 훑은 것)"
    text = f"최근 {summary['days']}일 {label}: 신호 {summary['n']}건, {summary['horizon']}봉 뒤 방향 적중 {summary['hit_rate']:.0%}"
    if summary.get("claimed_win_rate") is not None:
        text += f" (당시 기록이 말한 승률 평균 {summary['claimed_win_rate']:.0%}, {summary['n_claimed']}건 기준)"
    return text + ". 패턴 연구 기록이며 거래 성과가 아닙니다."

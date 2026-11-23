"""The operator's own trade calls, recorded and graded. Nothing here places an order.

A 10-year study found no cost-surviving edge in the lab's patterns, analogs or
context cells, so the lab's job is review: the user decides, writes the call
down, and the lab grades it afterwards from stored 5-minute bars.

An entry is one call: symbol, side (long / short / flat = 관망), the price and
time it was made, an optional stop and target, contracts, a free-text reason and
tags. It is closed by a manual exit or, when the user does nothing, automatically
at the first of stop, target or the horizon (default 12 hours of 5-minute bars).

Grading rules (all from bars, all after the entry bar):

* The path starts at the bar AFTER the one the entry fell in. What happened
  inside the entry bar after the entry is unknowable from a bar, so it is left out.
* A bar that touches both stop and target counts as the stop (the same
  convention the signal ledger uses) and the grade says it was ambiguous.
* Money goes through ``ContractSpec.pnl``: one tick of slippage on both sides and
  the commission, so the figure is after costs. R = net money / money risked
  between entry and stop (before costs); it needs a stop.
* A manual exit is graded at the user's price. Whether the plan's stop or target
  would have been hit first is reported separately (``plan_first``), so "I ignored
  my stop" is visible.
* What the lab said at the moment of the entry (signals, context tags, the stored
  analog snapshot) is captured when the entry is saved, from data up to the bar
  before the entry bar only. It is never recomputed later.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .contracts import CONTRACTS
from .data import INTERVAL_MAX_DAYS, Bar

BAR_SECONDS = 300
LAB_SYMBOLS = ("GC=F", "NQ=F")
SIDES = ("long", "short", "flat")
SIDE_KO = {"long": "롱", "short": "숏", "flat": "관망"}
PRESET_TAGS = ("추세추종", "역추세", "돌파", "지표발표", "뉴스")
MAX_TAGS = 6
MAX_TAG_LEN = 12
MAX_REASON = 500
DEFAULT_HORIZON_BARS = 144            # 12 hours of 5-minute bars
MIN_HORIZON_BARS = 12
MAX_HORIZON_BARS = 2016               # one week
MAX_CONTRACTS = 100
FUTURE_SLACK_SECONDS = 120
MAX_AGE_DAYS = 400
PRICE_SANITY = 0.05                   # an entry price this far from the bar it was made in is a typo
SIGNAL_LOOKBACK_BARS = 12             # "what the lab said" = signals of the last hour before the entry
SMALL_SAMPLE = 30
PRECISION = {"GC=F": 1, "NQ=F": 2}


class JournalError(ValueError):
    """A rejected entry; the message is Korean and shown to the user."""


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _utc(value).astimezone(timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise JournalError("시각이 비어 있습니다")
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00"))).astimezone(timezone.utc)
    except ValueError as exc:
        raise JournalError(f"시각을 읽을 수 없습니다: {text[:40]}") from exc


def bar_open(ts: datetime) -> float:
    """Open time (epoch seconds) of the 5-minute bar a moment falls in."""

    return (int(ts.timestamp()) // BAR_SECONDS) * BAR_SECONDS


def _number(raw: Any, label: str, *, required: bool = False) -> float | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise JournalError(f"{label}을(를) 입력하세요")
        return None
    try:
        value = float(str(raw).replace(",", ""))
    except ValueError as exc:
        raise JournalError(f"{label}이(가) 숫자가 아닙니다") from exc
    if not (value > 0) or value != value or value == float("inf"):
        raise JournalError(f"{label}은(는) 0보다 커야 합니다")
    return value


# --------------------------------------------------------------------------
# validating an entry
# --------------------------------------------------------------------------
def clean_tags(raw: Any) -> list[str]:
    out: list[str] = []
    for tag in raw if isinstance(raw, (list, tuple)) else []:
        text = " ".join(str(tag).split())[:MAX_TAG_LEN]
        if text and text not in out:
            out.append(text)
    return out[:MAX_TAGS]


def clean_entry(raw: Mapping[str, Any], *, now: datetime | None = None, existing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The stored shape of an entry, or a ``JournalError``. ``existing`` is the entry being edited.

    The stored snapshot of what the lab said (``lab``) is never taken from the
    request: only ``attach_lab`` writes it.
    """

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = dict(existing or {})
    merged = {**base, **{k: v for k, v in raw.items() if k in _EDITABLE}}
    symbol = str(merged.get("symbol") or "")
    if symbol not in LAB_SYMBOLS:
        raise JournalError("종목은 GC=F 또는 NQ=F만 기록합니다")
    side = str(merged.get("side") or "")
    if side not in SIDES:
        raise JournalError("방향은 롱·숏·관망 중 하나입니다")
    interval = str(merged.get("interval") or "5m")
    if interval not in INTERVAL_MAX_DAYS:
        raise JournalError("보던 봉 간격이 올바르지 않습니다")

    entry_ts = parse_ts(merged.get("entry_ts") or now)
    if (entry_ts - now).total_seconds() > FUTURE_SLACK_SECONDS:
        raise JournalError("진입 시각이 미래입니다")
    if now - entry_ts > timedelta(days=MAX_AGE_DAYS):
        raise JournalError("진입 시각이 너무 오래됐습니다")
    entry_price = _number(merged.get("entry_price"), "기록 가격", required=True)

    stop = _number(merged.get("stop"), "스톱")
    target = _number(merged.get("target"), "목표")
    if side == "long":
        if stop is not None and stop >= entry_price:
            raise JournalError("롱의 스톱은 기록 가격보다 아래여야 합니다")
        if target is not None and target <= entry_price:
            raise JournalError("롱의 목표는 기록 가격보다 위여야 합니다")
    elif side == "short":
        if stop is not None and stop <= entry_price:
            raise JournalError("숏의 스톱은 기록 가격보다 위여야 합니다")
        if target is not None and target >= entry_price:
            raise JournalError("숏의 목표는 기록 가격보다 아래여야 합니다")
    else:
        stop = target = None

    contracts = merged.get("contracts")
    try:
        contracts = int(contracts) if contracts not in (None, "") else 1
    except (TypeError, ValueError) as exc:
        raise JournalError("계약 수가 숫자가 아닙니다") from exc
    if not 1 <= contracts <= MAX_CONTRACTS:
        raise JournalError(f"계약 수는 1~{MAX_CONTRACTS}개입니다")

    exit_ts_raw, exit_price_raw = merged.get("exit_ts"), merged.get("exit_price")
    has_exit_ts = exit_ts_raw not in (None, "")
    has_exit_price = exit_price_raw not in (None, "")
    if side == "flat" and (has_exit_ts or has_exit_price):
        raise JournalError("관망에는 종료 가격이 없습니다")
    if has_exit_ts != has_exit_price:
        raise JournalError("종료 시각과 종료 가격을 함께 입력하세요")
    exit_ts = exit_price = None
    if has_exit_ts:
        exit_ts = parse_ts(exit_ts_raw)
        exit_price = _number(exit_price_raw, "종료 가격", required=True)
        if exit_ts <= entry_ts:
            raise JournalError("종료 시각은 진입 시각 뒤여야 합니다")
        if (exit_ts - now).total_seconds() > FUTURE_SLACK_SECONDS:
            raise JournalError("종료 시각이 미래입니다")

    horizon = merged.get("horizon_bars")
    try:
        horizon = int(horizon) if horizon not in (None, "") else DEFAULT_HORIZON_BARS
    except (TypeError, ValueError) as exc:
        raise JournalError("자동 종료 봉 수가 숫자가 아닙니다") from exc
    horizon = max(MIN_HORIZON_BARS, min(MAX_HORIZON_BARS, horizon))

    reason = " ".join(str(merged.get("reason") or "").split())[:MAX_REASON]
    entry = {
        "id": str(base.get("id") or uuid.uuid4().hex[:12]),
        "symbol": symbol,
        "interval": interval,
        "side": side,
        "entry_ts": entry_ts.isoformat(),
        "entry_price": entry_price,
        "stop": stop,
        "target": target,
        "contracts": contracts,
        "reason": reason,
        "tags": clean_tags(merged.get("tags")),
        "exit_ts": exit_ts.isoformat() if exit_ts else None,
        "exit_price": exit_price,
        "horizon_bars": horizon,
        "created_at": str(base.get("created_at") or now.isoformat()),
        "updated_at": now.isoformat(),
    }
    if base.get("lab") is not None:
        entry["lab"] = base["lab"]
    return entry


_EDITABLE = {"symbol", "interval", "side", "entry_ts", "entry_price", "stop", "target", "contracts", "reason", "tags", "exit_ts", "exit_price", "horizon_bars"}


def check_price_against_bars(entry: Mapping[str, Any], bars: Sequence[Bar]) -> None:
    """Reject a price that is nowhere near the market at that time (a typo, not a trade)."""

    at = bar_open(parse_ts(entry["entry_ts"]))
    near = [b for b in bars if abs(b.timestamp.timestamp() - at) <= 3 * BAR_SECONDS]
    if not near:
        return
    low, high = min(b.low for b in near), max(b.high for b in near)
    price = float(entry["entry_price"])
    if price < low * (1 - PRICE_SANITY) or price > high * (1 + PRICE_SANITY):
        raise JournalError(f"기록 가격이 그 시각 시세({low:,.2f} ~ {high:,.2f})와 크게 다릅니다")


# --------------------------------------------------------------------------
# what the lab said at that moment (point in time)
# --------------------------------------------------------------------------
def lab_snapshot(
    entry: Mapping[str, Any],
    bars: Sequence[Bar],
    signals: Sequence[Mapping[str, Any]] = (),
    analogs: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Signals, context tags and analog summary as known before the entry bar opened.

    Only bars that finished before the entry bar and signals recorded on those
    bars are used. The analog snapshot is the stored one, kept only if it was
    computed before the entry and from a bar no later than the entry bar.
    """

    now = now or datetime.now(timezone.utc)
    entry_ts = parse_ts(entry["entry_ts"])
    open_at = bar_open(entry_ts)
    prior = sorted((b for b in bars if b.timestamp.timestamp() < open_at), key=lambda b: b.timestamp)
    snap: dict[str, Any] = {
        "captured_at": now.isoformat(),
        "live": (now - entry_ts).total_seconds() <= 15 * 60,
        "bar_before": prior[-1].timestamp.isoformat() if prior else None,
        "context": None,
        "signals": [],
        "signal_counts": {"bullish": 0, "bearish": 0},
        "analogs": None,
        "notes": [],
    }
    if len(prior) >= 60:
        from .context import ContextTagger

        window = prior[-800:]
        ctx = ContextTagger(window, interval="5m").tag(len(window) - 1)
        snap["context"] = {key: value for key, value in ctx.as_dict().items() if key in ("session", "trend", "vol", "event")}
        if prior and open_at - prior[-1].timestamp.timestamp() > 6 * 3600:
            snap["notes"].append("직전 완성 봉이 6시간 넘게 떨어져 있어 맥락이 그 시각과 다를 수 있습니다")
    else:
        snap["notes"].append("진입 이전 봉이 부족해 맥락을 계산하지 못했습니다")

    first = open_at - SIGNAL_LOOKBACK_BARS * BAR_SECONDS
    recent = []
    for sig in signals:
        raw = sig.get("ts")
        stamp = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
        seconds = _utc(stamp).timestamp()
        if first <= seconds < open_at:
            recent.append((seconds, sig))
    recent.sort(key=lambda item: item[0], reverse=True)
    for _seconds, sig in recent:
        snap["signal_counts"]["bullish" if sig.get("direction") == "bullish" else "bearish"] += 1
    for seconds, sig in recent[:8]:
        claim = ((sig.get("claim") or {}).get("12") or {}).get("win_rate")
        snap["signals"].append({
            "ts": datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(),
            "pattern": sig.get("pattern"),
            "label": sig.get("label") or sig.get("pattern"),
            "direction": sig.get("direction"),
            "claim_win_rate_12": claim,
        })

    if analogs and analogs.get("analogs") and analogs.get("last_bar") and analogs.get("computed_at"):
        try:
            last_bar = _utc(datetime.fromisoformat(str(analogs["last_bar"]))).timestamp()
            computed = _utc(datetime.fromisoformat(str(analogs["computed_at"]))).timestamp()
        except ValueError:
            last_bar = computed = None
        if last_bar is not None and last_bar <= open_at and computed <= entry_ts.timestamp() + BAR_SECONDS and open_at - last_bar <= 3 * 3600:
            snap["analogs"] = {
                "computed_at": analogs["computed_at"],
                "last_bar": analogs["last_bar"],
                "summary": {str(h): {k: v for k, v in (analogs.get("summary") or {}).get(str(h), {}).items() if k in ("n", "up", "down", "share_up", "median")} for h in analogs.get("horizons") or [] if (analogs.get("summary") or {}).get(str(h))},
            }
        else:
            snap["notes"].append("그 시각 이전에 계산된 닮은 차트 스냅샷이 없어 비웠습니다")
    else:
        snap["notes"].append("닮은 차트 스냅샷이 저장돼 있지 않습니다")
    return snap


def alignment(entry: Mapping[str, Any], lab: Mapping[str, Any] | None) -> dict[str, Any]:
    """How the call sat against the lab's own reading of that moment (descriptive, not a verdict)."""

    side = entry.get("side")
    out = {"signals": "none", "trend": "unknown", "tag_flags": []}
    if not lab or side not in ("long", "short"):
        return out
    counts = lab.get("signal_counts") or {}
    bull, bear = int(counts.get("bullish") or 0), int(counts.get("bearish") or 0)
    if bull or bear:
        lean = "long" if bull > bear else "short" if bear > bull else "mixed"
        out["signals"] = "mixed" if lean == "mixed" else ("agree" if lean == side else "against")
    trend = (lab.get("context") or {}).get("trend")
    if trend in ("up", "down"):
        out["trend"] = "with" if (trend == "up") == (side == "long") else "against"
    elif trend == "range":
        out["trend"] = "range"
    tags = set(entry.get("tags") or [])
    if "추세추종" in tags and out["trend"] == "against":
        out["tag_flags"].append("추세추종이라 적었지만 그 시각 추세 태그는 반대 방향")
    if "역추세" in tags and out["trend"] == "with":
        out["tag_flags"].append("역추세라 적었지만 그 시각 추세 태그는 같은 방향")
    return out


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------
def _points(symbol: str, value: float) -> float:
    return round(value, PRECISION.get(symbol, 2))


def grade_entry(entry: Mapping[str, Any], bars: Sequence[Bar], *, now: datetime | None = None) -> dict[str, Any]:
    """Result of one entry from the 5-minute bars after it. Pure; the same inputs give the same grade."""

    now = now or datetime.now(timezone.utc)
    symbol, side = entry["symbol"], entry["side"]
    spec = CONTRACTS[symbol]
    contracts = int(entry.get("contracts") or 1)
    entry_ts = parse_ts(entry["entry_ts"])
    price0 = float(entry["entry_price"])
    stop = float(entry["stop"]) if entry.get("stop") else None
    target = float(entry["target"]) if entry.get("target") else None
    horizon = int(entry.get("horizon_bars") or DEFAULT_HORIZON_BARS)
    manual = bool(entry.get("exit_ts"))
    exit_manual_ts = parse_ts(entry["exit_ts"]) if manual else None
    long = side != "short"
    sign = 1.0 if long else -1.0
    first_open = bar_open(entry_ts) + BAR_SECONDS
    horizon_ts = entry_ts.timestamp() + horizon * BAR_SECONDS
    limit = exit_manual_ts.timestamp() if manual else horizon_ts

    path: list[Bar] = []
    for bar in sorted(bars, key=lambda b: b.timestamp):
        opened = bar.timestamp.timestamp()
        if opened < first_open:
            continue
        if opened >= limit:
            break
        if manual and opened + BAR_SECONDS > limit:
            break                                  # the bar the exit fell in also holds what came after it
        path.append(bar)

    notes: list[str] = []
    touch = None            # (index, 'stop'|'target')
    ambiguous = False
    if side != "flat":
        for index, bar in enumerate(path):
            hit_stop = stop is not None and (bar.low <= stop if long else bar.high >= stop)
            hit_target = target is not None and (bar.high >= target if long else bar.low <= target)
            if hit_stop or hit_target:
                touch = (index, "stop" if hit_stop else "target")
                ambiguous = hit_stop and hit_target
                break
    plan_first = touch[1] if touch else "none"

    horizon_done = now.timestamp() >= horizon_ts
    exit_reason, exit_price, exit_at = "open", None, None
    if side == "flat":
        exit_reason = "horizon" if horizon_done else "open"
    elif manual:
        exit_reason, exit_price, exit_at = "manual", float(entry["exit_price"]), exit_manual_ts
    elif touch:
        exit_reason = touch[1]
        exit_price = stop if touch[1] == "stop" else target
        exit_at = path[touch[0]].timestamp + timedelta(seconds=BAR_SECONDS)
    elif horizon_done:
        exit_reason = "horizon"
        exit_price = path[-1].close if path else price0
        exit_at = datetime.fromtimestamp(horizon_ts, tz=timezone.utc)

    # the part of the path the position lived through, for MFE / MAE
    lived = path[: touch[0] + 1] if (touch and not manual and side != "flat") else path
    highs = [b.high for b in lived] + ([exit_price] if exit_price is not None else [])
    lows = [b.low for b in lived] + ([exit_price] if exit_price is not None else [])
    up_max = max([h - price0 for h in highs], default=0.0)
    down_max = max([price0 - l for l in lows], default=0.0)
    up_max, down_max = max(up_max, 0.0), max(down_max, 0.0)
    last_close = path[-1].close if path else price0
    result: dict[str, Any] = {
        "id": entry.get("id"),
        "status": "open",
        "exit_reason": exit_reason,
        "plan_first": plan_first,
        "plan_ambiguous": ambiguous,
        "bars_seen": len(path),
        "notes": notes,
        "last_price": _points(symbol, last_close),
    }

    if side == "flat":
        move = last_close - price0
        result.update({
            "status": "closed" if horizon_done else "open",
            "result": "watch",
            "move_points": _points(symbol, move),
            "move_pct": round(move / price0 * 100, 3),
            "up_max_points": _points(symbol, up_max),
            "down_max_points": _points(symbol, down_max),
            "exit_price": _points(symbol, last_close) if horizon_done else None,
            "alignment": alignment(entry, entry.get("lab")),
        })
        return result

    mfe, mae = (up_max, down_max) if long else (down_max, up_max)
    money = spec.multiplier * contracts
    risk_points = abs(price0 - stop) if stop is not None else None
    risk_usd = risk_points * money if risk_points else None
    mark = exit_price if exit_price is not None else last_close
    gross = (mark - price0) * sign * money
    net = spec.pnl(price0, mark, contracts=contracts, long=long)
    cost = gross - net
    closed = exit_reason != "open"
    result.update({
        "status": "closed" if closed else "open",
        "result": ("win" if net > 0 else "loss" if net < 0 else "even") if closed else "open",
        "exit_price": _points(symbol, exit_price) if closed else None,
        "exit_ts": exit_at.isoformat() if exit_at else None,
        "gross_usd": round(gross, 2),
        "cost_usd": round(cost, 2),
        "net_usd": round(net, 2),
        "risk_points": _points(symbol, risk_points) if risk_points else None,
        "risk_usd": round(risk_usd, 2) if risk_usd else None,
        "r_net": round(net / risk_usd, 2) if risk_usd else None,
        "r_gross": round(gross / risk_usd, 2) if risk_usd else None,
        "mfe_points": _points(symbol, mfe),
        "mae_points": _points(symbol, mae),
        "mfe_usd": round(mfe * money, 2),
        "mae_usd": round(mae * money, 2),
        "mfe_r": round(mfe / risk_points, 2) if risk_points else None,
        "mae_r": round(mae / risk_points, 2) if risk_points else None,
        "held_minutes": round(((exit_at or now) - entry_ts).total_seconds() / 60) if (exit_at or now) else None,
        "alignment": alignment(entry, entry.get("lab")),
    })
    if not closed:
        result["unrealized"] = True
    if manual and touch:
        result["notes"].append("계획한 " + ("스톱" if plan_first == "stop" else "목표") + " 가격에 먼저 닿은 뒤 직접 종료했습니다")
    if ambiguous:
        result["notes"].append("한 봉이 스톱과 목표에 모두 닿아 스톱으로 처리했습니다")
    if closed and not path and exit_reason == "horizon":
        result["notes"].append("진입 뒤 봉이 아직 없습니다")
    return result


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------
def _bucket(rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, Any]:
    closed = [(e, g) for e, g in rows if g.get("status") == "closed" and e.get("side") in ("long", "short")]
    wins = sum(1 for _e, g in closed if g["result"] == "win")
    rs = [g["r_net"] for _e, g in closed if g.get("r_net") is not None]
    return {
        "n": len(closed),
        "wins": wins,
        "hit_rate": round(wins / len(closed), 4) if closed else None,
        "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "r_n": len(rs),
        "net_usd": round(sum(g["net_usd"] for _e, g in closed), 2),
        "small_sample": len(closed) < SMALL_SAMPLE,
    }


def journal_stats(rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, Any]:
    """Running totals over graded entries, overall and by tag, side and how the call sat against the lab."""

    rows = list(rows)
    total = _bucket(rows)
    total["open"] = sum(1 for _e, g in rows if g.get("status") == "open" and _e.get("side") != "flat")
    total["watch"] = sum(1 for e, _g in rows if e.get("side") == "flat")
    tags: dict[str, list] = {}
    for e, g in rows:
        for tag in e.get("tags") or []:
            tags.setdefault(tag, []).append((e, g))
    by_tag = {tag: _bucket(items) for tag, items in tags.items()}
    by_tag = {k: v for k, v in sorted(by_tag.items(), key=lambda kv: (-kv[1]["n"], kv[0])) if v["n"]}
    by_side = {side: _bucket([(e, g) for e, g in rows if e.get("side") == side]) for side in ("long", "short")}
    by_trend = {}
    by_signal = {}
    for key in ("with", "against", "range"):
        part = [(e, g) for e, g in rows if (g.get("alignment") or {}).get("trend") == key]
        if part:
            by_trend[key] = _bucket(part)
    for key in ("agree", "against", "mixed", "none"):
        part = [(e, g) for e, g in rows if (g.get("alignment") or {}).get("signals") == key and e.get("side") in ("long", "short")]
        if part:
            by_signal[key] = _bucket(part)
    return {"total": total, "by_tag": by_tag, "by_side": by_side, "by_trend": by_trend, "by_signal": by_signal}


# --------------------------------------------------------------------------
# service: bars, storage, the whole list
# --------------------------------------------------------------------------
def load_bars(repo: Any, symbol: str, since: datetime) -> list[Bar]:
    rows: list[Mapping[str, Any]] = []
    if repo is not None:
        try:
            rows = repo.goldlab_load_bars(symbol, "5m", since=since)
        except Exception:  # noqa: BLE001 - the file copy stands in
            rows = []
    if rows:
        return [Bar(timestamp=_utc(r["ts"]), open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r["volume"], source=r.get("source") or "yahoo") for r in rows]
    from .barstore import read_cache

    cached = read_cache(symbol, "5m")
    return [b for b in (cached.bars if cached else ()) if b.timestamp >= since]


_FRESH: dict[str, tuple[float, list[Bar]]] = {}
FRESH_SECONDS = 30


def fresh_bars(symbol: str) -> list[Bar]:
    """The vendor's newest 5-minute window, for entries still open (cached for a moment; [] when unreachable)."""

    hit = _FRESH.get(symbol)
    if hit and time.monotonic() - hit[0] < FRESH_SECONDS:
        return hit[1]
    try:
        from .data import fetch_bars

        bars = list(fetch_bars(symbol, interval="5m", days=2).bars)
    except Exception:  # noqa: BLE001
        bars = []
    _FRESH[symbol] = (time.monotonic(), bars)
    return bars


def merged_bars(repo: Any, symbol: str, since: datetime, *, with_fresh: bool) -> list[Bar]:
    bars = load_bars(repo, symbol, since)
    if with_fresh:
        from .barstore import merge_bars

        extra = [b for b in fresh_bars(symbol) if b.timestamp >= since]
        if extra:
            bars = list(merge_bars(bars, extra, refresh_tail=12))
    return bars


def capture_lab(repo: Any, entry: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """The snapshot of what the lab said, from stored bars, the ledger and the stored analogs."""

    from .analogs import load_stored_analogs
    from .ledger import open_ledger

    entry_ts = parse_ts(entry["entry_ts"])
    bars = load_bars(repo, entry["symbol"], entry_ts - timedelta(days=5))
    try:
        signals = open_ledger(entry["symbol"], "5m", repo=repo).all()
    except Exception:  # noqa: BLE001
        signals = []
    try:
        analogs = load_stored_analogs(repo, entry["symbol"], "5m")
    except Exception:  # noqa: BLE001
        analogs = None
    return lab_snapshot(entry, bars, signals, analogs, now=now)


def create_entry(repo: Any, raw: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    entry = clean_entry(raw, now=now)
    entry_ts = parse_ts(entry["entry_ts"])
    check_price_against_bars(entry, load_bars(repo, entry["symbol"], entry_ts - timedelta(hours=1)))
    entry["lab"] = capture_lab(repo, entry, now=now)
    repo.goldlab_journal_save(entry)
    return entry


def update_entry(repo: Any, entry_id: str, raw: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    existing = repo.goldlab_journal_get(entry_id)
    if existing is None:
        return None
    entry = clean_entry(raw, now=now, existing=existing)
    moved = any(entry[k] != existing.get(k) for k in ("symbol", "entry_ts", "side"))
    if moved:
        check_price_against_bars(entry, load_bars(repo, entry["symbol"], parse_ts(entry["entry_ts"]) - timedelta(hours=1)))
        entry["lab"] = capture_lab(repo, entry, now=now)
    repo.goldlab_journal_save(entry)
    return entry


def graded_list(repo: Any, symbol: str | None = None, *, limit: int = 60, since: datetime | None = None, until: datetime | None = None, now: datetime | None = None, with_fresh: bool = True) -> dict[str, Any]:
    """Entries with their grades, newest first, plus the running stats."""

    now = now or datetime.now(timezone.utc)
    entries = repo.goldlab_journal_list(symbol, since=since, until=until, limit=limit)
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_symbol.setdefault(entry["symbol"], []).append(entry)
    for sym, items in by_symbol.items():
        oldest = min(parse_ts(e["entry_ts"]) for e in items)
        pending = any(not e.get("exit_ts") and (now - parse_ts(e["entry_ts"])).total_seconds() < (int(e.get("horizon_bars") or DEFAULT_HORIZON_BARS) * BAR_SECONDS + 3600) for e in items)
        bars = merged_bars(repo, sym, oldest - timedelta(minutes=10), with_fresh=with_fresh and pending)
        for entry in items:
            rows.append((entry, grade_entry(entry, bars, now=now)))
    rows.sort(key=lambda pair: pair[0]["entry_ts"], reverse=True)
    return {
        "entries": [{**entry, "grade": grade} for entry, grade in rows],
        "stats": journal_stats(rows),
        "tags": list(PRESET_TAGS),
        "generated_at": now.isoformat(),
    }


# --------------------------------------------------------------------------
# for the review note: the day's entries as evidence text
# --------------------------------------------------------------------------
def _kst(stamp: str, fmt: str = "%H:%M") -> str:
    from zoneinfo import ZoneInfo

    return parse_ts(stamp).astimezone(ZoneInfo("Asia/Seoul")).strftime(fmt)


def evidence_lines(rows: Sequence[Mapping[str, Any]], *, recent: Mapping[str, Any] | None = None) -> list[tuple[str, str]]:
    """(key, text) pairs for the evidence pack from graded entries (each row = entry + ``grade``).

    Wording avoids the words the note's guard reads as trade advice ("진입",
    "청산", "손절"): the user's call is a "기록", the end of it a "종료".
    """

    out: list[tuple[str, str]] = []
    if not rows:
        return out
    stats = journal_stats([(r, r["grade"]) for r in rows])["total"]
    out.append((
        "journal_summary",
        f"내 판단 기록: 이 복기 구간에 직접 기록한 판단 {len(rows)}건 (종료 {stats['n']}건, 진행 중 {stats['open']}건, 관망 {stats['watch']}건). "
        + (f"종료한 {stats['n']}건 중 이익 {stats['wins']}건, 비용 뺀 손익 합계 {stats['net_usd']:+,.2f}달러." if stats["n"] else "아직 종료된 판단이 없습니다.")
        + " 손익은 슬리피지·수수료를 뺀 값이고, 연구소의 신호 채점('맞음')과는 다른 기준입니다.",
    ))
    for i, row in enumerate(rows[:8], 1):
        g = row["grade"]
        side = SIDE_KO[row["side"]]
        head = f"내 판단 {i}: {row['symbol']} {side} 기록 {_kst(row['entry_ts'])} KST, 기록 가격 {row['entry_price']:,}"
        if row.get("stop"):
            head += f", 계획한 스톱 {row['stop']:,}"
        if row.get("target"):
            head += f", 계획한 목표 {row['target']:,}"
        head += f", {row.get('contracts', 1)}계약."
        if row.get("tags"):
            head += " 태그 " + "·".join(row["tags"]) + "."
        if row.get("reason"):
            head += f" 적어 둔 이유: {row['reason'][:100]}."
        if row["side"] == "flat":
            tail = (f" 관망 뒤 {g['bars_seen']}봉 동안 가격 변화 {g['move_points']:+,}포인트 ({g['move_pct']:+.2f}%), 위로 최대 {g['up_max_points']:,}포인트, 아래로 최대 {g['down_max_points']:,}포인트."
                    if g.get("bars_seen") else " 이후 봉이 아직 없습니다.")
        elif g["status"] == "open":
            tail = f" 아직 종료 전입니다. 지금 가격 {g['last_price']:,} 기준 평가손익 {g['net_usd']:+,.2f}달러 (비용 반영)."
        else:
            reason = {"manual": "직접 종료", "stop": "스톱에 닿아 종료", "target": "목표에 닿아 종료", "horizon": "정해 둔 시간이 지나 종료"}[g["exit_reason"]]
            tail = f" 결과: {reason}, 종료 가격 {g['exit_price']:,}, 비용 뺀 손익 {g['net_usd']:+,.2f}달러"
            if g.get("r_net") is not None:
                tail += f", R {g['r_net']:+.2f}"
            tail += f". 보유 중 유리하게 간 최대 {g['mfe_points']:,}포인트, 불리하게 간 최대 {g['mae_points']:,}포인트."
            if g.get("plan_first") in ("stop", "target") and g["exit_reason"] == "manual":
                tail += " 계획한 " + ("스톱" if g["plan_first"] == "stop" else "목표") + " 가격에 먼저 닿았습니다."
        lab = row.get("lab") or {}
        al = g.get("alignment") or {}
        bits = []
        ctx = lab.get("context")
        if ctx:
            bits.append("그 시각 맥락 태그 " + ", ".join(f"{k} {v}" for k, v in ctx.items()))
        counts = lab.get("signal_counts") or {}
        if counts.get("bullish") or counts.get("bearish"):
            bits.append(f"직전 1시간 연구소 신호 ▲ {counts.get('bullish', 0)}건, ▼ {counts.get('bearish', 0)}건")
        elif lab:
            bits.append("직전 1시간 연구소 신호 없음")
        an = (lab.get("analogs") or {}).get("summary") or {}
        if an:
            h = sorted(an, key=int)[0]
            bits.append(f"닮은 차트 {h}봉 뒤 상승 비율 {an[h]['share_up'] * 100:.1f}%")
        rel = {"agree": "기록한 방향과 신호가 같은 쪽", "against": "기록한 방향과 신호가 반대쪽", "mixed": "신호가 엇갈림"}.get(al.get("signals"))
        trend_rel = {"with": "추세 태그와 같은 방향", "against": "추세 태그와 반대 방향", "range": "추세 태그는 횡보"}.get(al.get("trend"))
        rels = [x for x in (rel, trend_rel) if x]
        if bits or rels:
            tail += " 연구소가 그 시각에 본 것: " + "; ".join(bits + rels) + "."
        for flag in al.get("tag_flags") or []:
            tail += f" ({flag})"
        out.append((f"journal_{row['id']}", head + tail))
    if recent and recent.get("by_tag"):
        parts = []
        for tag, b in list(recent["by_tag"].items())[:5]:
            part = f"{tag} {b['n']}건 중 이익 {b['wins']}건"
            if b.get("avg_r") is not None:
                part += f", 평균 R {b['avg_r']:+.2f}"
            part += f", 손익 {b['net_usd']:+,.2f}달러"
            parts.append(part)
        t = recent["total"]
        out.append((
            "journal_tags",
            f"최근 {recent.get('days', 30)}일 내 판단 누적: 종료 {t['n']}건 중 이익 {t['wins']}건"
            + (f", 평균 R {t['avg_r']:+.2f}" if t.get("avg_r") is not None else "")
            + f", 손익 합계 {t['net_usd']:+,.2f}달러. 태그별: " + "; ".join(parts) + "."
            + (f" 종료 {t['n']}건은 통계로 말하기에 표본이 작습니다." if t["small_sample"] else ""),
        ))
    return out

"""The daily review note ("AI 복기 노트"): a three-model debate over a code-built evidence pack.

Research and review only. The note looks back at what the lab recorded on the last
trading day and how it turned out. It does not forecast and it does not advise a
trade, and the lab's own ten-year record says why it must not: single patterns and
similar-chart analogs showed no lasting directional edge after costs.

Three rules keep the models honest.

1. Every number comes from the *evidence pack*, which this module builds with plain
   code from the ledger, the stored studies, the analogs snapshot and the bars. A
   model may quote a number by its id (E12) and may not make one up.
2. Four turns: an analyst drafts (Claude), a critic attacks the draft and proposes
   up to three testable hypotheses (GPT), a verifier checks every number and claim
   against the pack (Gemini), and the analyst writes the final note.
3. After the last turn a deterministic guard extracts every number from the final
   note and drops each sentence whose numbers are not in the pack. It also drops
   sentences that read as trade advice. What it removed is recorded.

Storage: one ``backtest_runs`` row per (symbol, review day), label
``gold:review:{symbol}:{YYYY-MM-DD}``. No new table. Hypotheses live inside that
row and the weekly job fills in their test results.

A "review day" is the KST trading day ending 07:00 (22:00 UTC, the Globex
settlement hour), dated by the KST day on which it ends.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .context import DIMENSIONS
from .data import Bar
from .ledger import wilson
from .sessions import SESSIONS, session_of

KST = ZoneInfo("Asia/Seoul")
REVIEW_INTERVAL = "5m"
HORIZONS = (4, 12, 24)              # the horizons the day's signals are judged at
STUDY_HORIZON = 12                  # the horizon the divergence check compares
DRIFT_DAYS = 30
MIN_WINDOW_BARS = 60                # a window with fewer 5-minute bars is not a trading day
MIN_SAMPLES = 30
LABEL_PREFIX = "gold:review"
MAX_ATTEMPTS = 2                    # a failed run is retried once, not every two hours
FOOTER = "과거 기록 복기이며 거래 권유가 아닙니다"
PRECISION = {"GC=F": 1, "NQ=F": 2}

DEFAULT_ANALYST = "anthropic:claude-sonnet-5"
DEFAULT_CRITIC = "openai:gpt-5.4"
DEFAULT_VERIFIER = "google:gemini-3.5-flash"
# USD per million tokens (input, output). Estimates: set GOLDLAB_REVIEW_PRICES to override.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.0, 15.0),
    "gpt-5.4": (2.5, 15.0),
    "gpt-5.4-mini": (0.75, 4.5),
    "gemini-3.5-flash": (0.5, 3.0),
}
FALLBACK_PRICE = (3.0, 15.0)

SECTIONS = (
    ("summary", "오늘 장 요약"),
    ("signals", "신호와 결과 (맞음/틀림)"),
    ("context", "상황별로 본 것"),
    ("drift", "기록이 흔들리는 패턴"),
    ("watch", "내일 볼 것 (관찰 포인트만)"),
    ("dissent", "이견"),
    ("hypotheses", "검증할 가설"),
)
SECTION_TITLES = dict(SECTIONS)
DRAFT_KEYS = ("summary", "signals", "context", "drift", "watch")

TREND_KO = {"up": "상승 추세", "down": "하락 추세", "range": "횡보"}
VOL_KO = {"low": "변동성 낮음", "mid": "변동성 보통", "high": "변동성 높음"}
EVENT_KO = {"near": "지표 발표 근처", "far": "지표와 먼 시간"}
SESSION_KO = {"us": "미국장", "europe": "유럽장", "asia": "아시아장", "off": "세션 밖"}
CONTEXT_VALUES = {
    "session": ("us", "europe", "asia", "off"),
    "trend": ("up", "down", "range"),
    "vol": ("low", "mid", "high"),
    "event": ("near", "far"),
}
DIM_ALIASES = {"volatility": "vol", "변동성": "vol", "세션": "session", "추세": "trend", "지표": "event", "events": "event"}
SESSION_ALIASES = {"미국": "us", "미국장": "us", "뉴욕": "us", "유럽": "europe", "유럽장": "europe", "런던": "europe", "아시아": "asia", "아시아장": "asia", "도쿄": "asia", "장외": "off", "세션밖": "off", "세션 밖": "off"}


# --------------------------------------------------------------------------
# the review day
# --------------------------------------------------------------------------
def window_for(day: date) -> tuple[datetime, datetime]:
    """The review day's bars: 07:00 KST the day before up to 07:00 KST on ``day``, in UTC."""

    end = datetime.combine(day, dtime(7, 0), tzinfo=KST)
    return (end - timedelta(days=1)).astimezone(timezone.utc), end.astimezone(timezone.utc)


def latest_review_day(now: datetime) -> date:
    """The newest review day that has finished at ``now``."""

    local = now.astimezone(KST)
    return local.date() if local.time() >= dtime(7, 0) else local.date() - timedelta(days=1)


def pick_review_day(bars: Sequence[Bar], now: datetime, *, lookback: int = 6, min_bars: int = MIN_WINDOW_BARS) -> date | None:
    """The newest finished review day that actually traded (weekends and holidays have no bars)."""

    first = latest_review_day(now)
    for back in range(lookback + 1):
        day = first - timedelta(days=back)
        start, end = window_for(day)
        if sum(1 for bar in bars if start <= bar.timestamp < end) >= min_bars:
            return day
    return None


def review_label(symbol: str, day: date | str) -> str:
    return f"{LABEL_PREFIX}:{symbol}:{day}"


# --------------------------------------------------------------------------
# the evidence pack
# --------------------------------------------------------------------------
class _Pack:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []
        self.by_key: dict[str, str] = {}

    def add(self, key: str, text: str) -> str:
        eid = f"E{len(self.items) + 1}"
        self.items.append({"id": eid, "key": key, "text": text})
        self.by_key[key] = eid
        return eid


def _kst(stamp: datetime | str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp)
    return stamp.astimezone(KST).strftime(fmt)


def _pct(value: float | None, digits: int = 1) -> str:
    return "없음" if value is None else f"{value * 100:.{digits}f}%"


def _spct(value: float | None, digits: int = 2) -> str:
    return "없음" if value is None else f"{value * 100:+.{digits}f}%"


def _arrow(direction: str) -> str:
    return "▲" if direction == "bullish" else "▼"


def _ts(row: Mapping[str, Any]) -> datetime:
    value = row["ts"]
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _graded(rows: Sequence[Mapping[str, Any]], horizon: int) -> list[Mapping[str, Any]]:
    return [row for row in rows if str(horizon) in (row.get("grades") or {})]


def _hits(rows: Sequence[Mapping[str, Any]], horizon: int) -> int:
    return sum(1 for row in rows if row["grades"][str(horizon)].get("hit"))


def _claim_mean(rows: Sequence[Mapping[str, Any]], horizon: int) -> tuple[float | None, int]:
    claims = [(row.get("claim") or {}).get(str(horizon), {}).get("win_rate") for row in rows]
    claims = [c for c in claims if c is not None]
    return (sum(claims) / len(claims) if claims else None), len(claims)


def _study_pooled(study: Mapping[str, Any] | None, pattern: str, horizon: int) -> Mapping[str, Any] | None:
    for row in (study or {}).get("patterns") or []:
        if row.get("pattern") == pattern:
            cell = (row.get("horizons") or {}).get(str(horizon))
            return cell if cell and cell.get("count") else None
    return None


def _study_reference(study: Mapping[str, Any] | None, horizon: int) -> tuple[float | None, int]:
    """Win rate of every pattern signal over the ten years at one horizon, weighted by count."""

    total = wins = 0.0
    for row in (study or {}).get("patterns") or []:
        cell = (row.get("horizons") or {}).get(str(horizon)) or {}
        count = int(cell.get("count") or 0)
        if count and cell.get("win_rate") is not None:
            total += count
            wins += count * float(cell["win_rate"])
    return (wins / total if total else None), int(total)


def build_evidence(
    symbol: str,
    day: date,
    *,
    bars: Sequence[Bar],
    signals: Sequence[Mapping[str, Any]],
    study: Mapping[str, Any] | None = None,
    study_1h: Mapping[str, Any] | None = None,
    analogs: Mapping[str, Any] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    upcoming: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Every number the note may use, each with a stable id. Pure: same inputs, same pack."""

    now = now or datetime.now(timezone.utc)
    prec = PRECISION.get(symbol, 2)
    start, end = window_for(day)
    day_bars = sorted((b for b in bars if start <= b.timestamp < end), key=lambda b: b.timestamp)
    day_sigs = sorted((s for s in signals if start <= _ts(s) < end), key=lambda s: (_ts(s), s["id"]))
    px = lambda v: f"{v:,.{prec}f}"  # noqa: E731
    pack = _Pack()

    # -- frame ------------------------------------------------------------
    ref = ""
    if study:
        ref = f"기준 기록은 10년 워크포워드 연구(5분봉 {int(study.get('bars') or 0):,}개, {str(study.get('start'))[:10]} ~ {str(study.get('end'))[:10]})입니다. "
    pack.add(
        "meta",
        f"{symbol} 복기 구간은 {_kst(start)} ~ {_kst(end)} (KST), 5분봉 {len(day_bars)}개입니다. {ref}"
        f"신호는 4봉·12봉·24봉 뒤 종가로 채점했고 연구 지평은 4·12·24·72봉입니다. 최근 비교 구간은 {DRIFT_DAYS}일, 표본 {MIN_SAMPLES}개 미만은 통계로 말할 수 없습니다. "
        f"'맞음'은 신호 방향으로 N봉 뒤 종가가 진입 종가보다 유리했다는 뜻이며 거래 손익이 아닙니다. 복기 시점은 {_kst(now)} (KST)입니다.",
    )

    # -- prices -----------------------------------------------------------
    if day_bars:
        high = max(day_bars, key=lambda b: b.high)
        low = min(day_bars, key=lambda b: b.low)
        first, last = day_bars[0], day_bars[-1]
        change = last.close - first.open
        pack.add(
            "price",
            f"시가 {px(first.open)}, 고가 {px(high.high)} ({_kst(high.timestamp, '%H:%M')} KST), 저가 {px(low.low)} ({_kst(low.timestamp, '%H:%M')} KST), "
            f"종가 {px(last.close)}. 등락 {change:+,.{prec}f} ({_spct(change / first.open)}), 고저 폭 {px(high.high - low.low)} ({_pct((high.high - low.low) / first.open, 2)}).",
        )
        for session in SESSIONS:
            inside = [b for b in day_bars if session_of(b.timestamp, session)]
            if not inside:
                continue
            hi, lo = max(b.high for b in inside), min(b.low for b in inside)
            chg = inside[-1].close - inside[0].open
            pack.add(
                f"session_{session.key}",
                f"{SESSION_KO[session.key]} 구간 ({_kst(inside[0].timestamp, '%H:%M')} ~ {_kst(inside[-1].timestamp, '%H:%M')} KST, 봉 {len(inside)}개): "
                f"시가 {px(inside[0].open)}, 고가 {px(hi)}, 저가 {px(lo)}, 종가 {px(inside[-1].close)}, 폭 {px(hi - lo)}, 등락 {chg:+,.{prec}f}.",
            )
    else:
        pack.add("price", "이 구간에는 5분봉이 없습니다.")

    # -- the day's signals -------------------------------------------------
    pending_note = "채점 대기는 해당 봉 수가 아직 지나지 않은 신호입니다."
    if day_sigs:
        ups = sum(1 for s in day_sigs if s["direction"] == "bullish")
        parts = []
        for h in HORIZONS:
            done = _graded(day_sigs, h)
            parts.append(f"{h}봉 뒤 채점 {len(done)}건 중 맞음 {_hits(done, h)}건 ({_pct(_hits(done, h) / len(done)) if done else '없음'}), 틀림 {len(done) - _hits(done, h)}건, 채점 대기 {len(day_sigs) - len(done)}건")
        pack.add("signals_total", f"하루 신호 {len(day_sigs)}건 (▲ {ups}건, ▼ {len(day_sigs) - ups}건, 패턴 {len({s['pattern'] for s in day_sigs})}종). " + "; ".join(parts) + ". " + pending_note)
        groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for s in day_sigs:
            groups.setdefault((s["pattern"], s["direction"]), []).append(s)
        ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for (pattern, direction), rows in ordered[:12]:
            bits = []
            for h in HORIZONS:
                done = _graded(rows, h)
                if done:
                    bits.append(f"{h}봉 뒤 맞음 {_hits(done, h)}/{len(done)} ({_pct(_hits(done, h) / len(done))})")
            mean, n_claim = _claim_mean(rows, STUDY_HORIZON)
            claim = f" 신호 당시 기록이 말한 {STUDY_HORIZON}봉 승률 평균 {_pct(mean)} ({n_claim}건 기준)." if mean is not None else " 신호 당시 기록에 승률 주장 없음."
            pack.add(
                f"sig_{pattern}_{direction}",
                f"{_arrow(direction)} {rows[0].get('label') or pattern} {len(rows)}건 (첫 {_kst(_ts(rows[0]), '%H:%M')}, 마지막 {_kst(_ts(rows[-1]), '%H:%M')} KST): "
                + (", ".join(bits) if bits else "아직 채점된 봉 수가 없음") + "." + claim,
            )
        rest = ordered[12:]
        if rest:
            n_rest = sum(len(rows) for _k, rows in rest)
            pack.add("sig_rest", f"그 밖의 패턴 그룹 {len(rest)}개에서 신호 {n_rest}건이 더 있었습니다 (개별 기록 생략).")
        # by context
        for dim in DIMENSIONS:
            labels = {"session": SESSION_KO, "trend": TREND_KO, "vol": VOL_KO, "event": EVENT_KO}[dim]
            for value in CONTEXT_VALUES[dim]:
                rows = [s for s in day_sigs if (s.get("context") or {}).get(dim) == value]
                if not rows:
                    continue
                done = _graded(rows, STUDY_HORIZON)
                tail = f"{STUDY_HORIZON}봉 뒤 채점 {len(done)}건 중 맞음 {_hits(done, STUDY_HORIZON)}건 ({_pct(_hits(done, STUDY_HORIZON) / len(done))})" if done else f"{STUDY_HORIZON}봉 뒤 채점된 신호 없음"
                pack.add(f"ctx_{dim}_{value}", f"상황 '{labels[value]}'에서 뜬 신호 {len(rows)}건: {tail}.")
    else:
        pack.add("signals_total", "이 구간에 기록된 신호가 없습니다.")

    # -- drift: the last 30 days against the ten-year record -----------------
    recent_from = end - timedelta(days=DRIFT_DAYS)
    recent = [s for s in signals if recent_from <= _ts(s) < end]
    origins: dict[str, int] = {}
    for s in recent:
        origins[s.get("origin", "?")] = origins.get(s.get("origin", "?"), 0) + 1
    live_first = min((_ts(s) for s in signals if s.get("origin") == "live"), default=None)
    parts = []
    for h in HORIZONS:
        done = _graded(recent, h)
        if not done:
            continue
        mean, n_claim = _claim_mean(done, h)
        ref_rate, ref_n = _study_reference(study, h)
        base = ((study or {}).get("base_rate") or {}).get(str(h)) or {}
        long_rate = (base.get("long") or {}).get("win_rate")
        short_rate = (base.get("short") or {}).get("win_rate")
        text = f"{h}봉 뒤: 최근 {DRIFT_DAYS}일 채점 {len(done)}건 중 맞음 {_hits(done, h)}건 ({_pct(_hits(done, h) / len(done))})"
        if mean is not None:
            text += f", 당시 기록이 말한 승률 평균 {_pct(mean)} ({n_claim}건)"
        if ref_rate is not None:
            text += f", 10년 기록의 전체 패턴 평균 적중 {_pct(ref_rate)} (표본 {ref_n:,}건)"
        if long_rate is not None and short_rate is not None:
            text += f", 아무 봉이나 골랐을 때 기준 승률은 롱 방향 {_pct(long_rate)}·숏 방향 {_pct(short_rate)}"
        parts.append(text)
    live_note = f" 실시간 기록은 {_kst(live_first, '%Y-%m-%d')}부터라 비교 구간이 짧을 수 있습니다." if live_first else ""
    pack.add(
        "drift",
        f"최근 {DRIFT_DAYS}일 기록 {len(recent)}건 (출처 " + ", ".join(f"{k} {v}건" for k, v in sorted(origins.items())) + ")." + live_note
        + (" " + "; ".join(parts) + "." if parts else " 채점된 신호가 아직 없습니다."),
    )

    # patterns whose live record departs from the study
    by_pattern: dict[str, list[Mapping[str, Any]]] = {}
    for s in recent:
        by_pattern.setdefault(s["pattern"], []).append(s)
    rows = []
    for pattern, group in by_pattern.items():
        done = _graded(group, STUDY_HORIZON)
        cell = _study_pooled(study, pattern, STUDY_HORIZON)
        if len(done) < 5 or not cell or cell.get("win_rate") is None:
            continue
        hits = _hits(done, STUDY_HORIZON)
        ci = wilson(hits, len(done))
        outside = ci is not None and not (ci[0] <= float(cell["win_rate"]) <= ci[1])
        rows.append((len(done), pattern, group[0].get("label") or pattern, group[0]["direction"], hits, ci, cell, outside))
    rows.sort(key=lambda r: (-r[0], r[1]))
    shown = rows[:8]
    for n, pattern, label, direction, hits, ci, cell, outside in shown:
        pack.add(
            f"div_{pattern}",
            f"{_arrow(direction)} {label}: 10년 기록 {STUDY_HORIZON}봉 승률 {_pct(cell['win_rate'])} (표본 {int(cell['count']):,}건, 기준 {_pct(cell.get('base_win_rate'))}) / "
            f"최근 {DRIFT_DAYS}일 {n}건 중 맞음 {hits}건 ({_pct(hits / n)}, 95% 구간 {_pct(ci[0])} ~ {_pct(ci[1])}). "
            + ("10년 기록 승률이 이 구간 밖입니다" if outside else "10년 기록 승률이 이 구간 안입니다") + (f" (표본 {MIN_SAMPLES}개 미만이라 우연일 수 있음)." if n < MIN_SAMPLES else "."),
        )
    n_out = sum(1 for r in rows if r[7])
    pack.add(
        "div_summary",
        f"최근 {DRIFT_DAYS}일 {STUDY_HORIZON}봉 채점이 5건 이상인 패턴 {len(rows)}종 중 10년 기록과 어긋난 패턴은 {n_out}종입니다."
        + (" 비교할 만한 패턴이 없습니다." if not rows else ""),
    )

    # -- macro events -------------------------------------------------------
    if events is None:
        from .events import macro_events

        events = macro_events(start, end, min_stars=2)
    if events:
        for event in events[:8]:
            pack.add(f"event_{event['timestamp']}", f"복기 구간 안 지표: {_kst(event['timestamp'])} KST {'★' * int(event['stars'])} {event['name']}.")
    else:
        pack.add("events_none", "복기 구간 안에 일정표에 있는 2성 이상 지표가 없습니다 (FOMC·CPI 등은 직접 입력한 일정만 반영).")
    if upcoming is None:
        from .events import macro_events

        upcoming = macro_events(end, end + timedelta(hours=48), min_stars=2)
    if upcoming:
        for event in upcoming[:6]:
            pack.add(f"upcoming_{event['timestamp']}", f"예정 지표: {_kst(event['timestamp'])} KST {'★' * int(event['stars'])} {event['name']}.")
    else:
        pack.add("upcoming_none", f"복기 구간 이후 48시간 안에 일정표에 있는 2성 이상 지표가 없습니다.")

    # -- similar past charts ------------------------------------------------
    if analogs and analogs.get("analogs"):
        last_bar = str(analogs.get("last_bar") or "")
        stale = last_bar and datetime.fromisoformat(last_bar) > end
        pack.add(
            "analogs_meta",
            f"닮은 과거 차트 스냅샷: 계산 {_kst(analogs['computed_at'])} KST, 마지막 봉 {_kst(last_bar) if last_bar else '없음'} KST, 최근 {analogs.get('window')}봉과 닮은 {len(analogs['analogs'])}곳."
            + (" 복기 구간이 끝난 뒤에 계산된 최신 스냅샷이라 복기 날짜의 차트와 다를 수 있습니다." if stale else " 복기 구간 안 시점의 스냅샷입니다.")
            + " 참고용 분포이며 예측이 아닙니다.",
        )
        for h in analogs.get("horizons") or []:
            s = (analogs.get("summary") or {}).get(str(h))
            if s:
                pack.add(
                    f"analogs_{h}",
                    f"닮은 곳 {h}봉 뒤: {s['n']}곳 중 상승 {s['up']}곳, 하락 {s['down']}곳 (상승 비율 {_pct(s['share_up'])}, 기준 {_pct(s.get('base_share_up'))}), 중앙값 {_spct(s['median'])}.",
                )
        validation = analogs.get("validation") or {}
        if validation:
            bits = []
            for h, r in sorted((validation.get("horizons") or {}).items(), key=lambda kv: int(kv[0])):
                if r.get("hit_rate") is not None:
                    p = r.get("p_vs_majority")
                    bits.append(f"{h}봉 뒤 적중 {_pct(r['hit_rate'])} (항상 다수 방향만 찍는 기준 {_pct(r.get('base'))}, 검증 {int(r.get('n') or 0):,}건" + (f", p값 {p:.3f}" if p is not None else "") + ")")
            pack.add("analogs_validation", f"닮은 차트 방식의 10년 순차 검증 결과: {validation.get('line')}. " + "; ".join(bits) + ".")
    else:
        pack.add("analogs_none", "닮은 과거 차트 스냅샷이 저장돼 있지 않습니다.")

    # -- the ten-year study -------------------------------------------------
    for name, one in (("5분봉", study), ("1시간봉", study_1h)):
        if not one:
            continue
        fdr = one.get("fdr") or {}
        sig = pos = 0
        for row in one.get("patterns") or []:
            for cell in (row.get("horizons") or {}).values():
                cells = [cell] + [c for dim in (cell.get("context") or {}).values() for c in dim.values()]
                for c in cells:
                    if c.get("fdr_significant"):
                        sig += 1
                        pos += 1 if (c.get("shrunk_edge_win_rate") or 0) > 0 else 0
        pack.add(
            f"study_{name}",
            f"10년 연구({name}): 패턴·봉 수·상황별로 나눈 {int(fdr.get('tested') or 0):,}칸을 거짓 발견율(FDR) 검사했을 때 통과한 칸은 {sig}칸입니다. "
            f"그중 기준 승률보다 높은 칸은 {pos}칸이고 나머지 {sig - pos}칸은 기준보다 낮았습니다. 통과한 칸이 곧 거래로 남는 우위는 아닙니다.",
        )
    return {
        "symbol": symbol,
        "date": str(day),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "bars": len(day_bars),
        "signals": len(day_sigs),
        "items": pack.items,
        "keys": dict(pack.by_key),
    }


def pack_text(pack: Mapping[str, Any]) -> str:
    return "\n".join(f"[{item['id']}] {item['text']}" for item in pack["items"])


def pack_ids(pack: Mapping[str, Any]) -> set[str]:
    return {item["id"] for item in pack["items"]}


# --------------------------------------------------------------------------
# the numeric guard
# --------------------------------------------------------------------------
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_TAG = re.compile(r"(?<![A-Za-z0-9])[EH]\d{1,3}(?!\d)")
_SENTENCE = re.compile(r"(?<=[.!?。])\s+|\n+")
_ADVICE = re.compile(
    r"매수|매도|(롱|숏)\s*(진입|포지션)|진입(하|해|을|\s*권|\s*추천)|청산(하|해)|손절(하|해|가)|사세요|파세요|사야|팔아야|추천(합|드)|비중\s*(확대|축소)|담으세요|"
    r"(오를|내릴|상승할|하락할|오를지|올라갈|내려갈)\s*(것|듯|가능성이 높)"
)


def extract_numbers(text: str) -> list[tuple[str, float, int]]:
    """(token, value, decimals) for every number in the text, without evidence tags like E12."""

    out = []
    for match in _NUMBER.finditer(_TAG.sub(" ", text)):
        token = match.group(0)
        plain = token.replace(",", "")
        out.append((token, float(plain), len(plain.split(".")[1]) if "." in plain else 0))
    return out


def _round_half_up(value: float, digits: int) -> float:
    return float(Decimal(repr(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def number_allowed(value: float, decimals: int, allowed: Sequence[float]) -> bool:
    """Exact, or the rounding of a pack number (54.3% written as 54%), or fraction/percent of one."""

    for a in allowed:
        if abs(value - a) < 1e-9:
            return True
    if decimals == 0 and value < 10:
        return False                      # a small whole number must be in the pack as itself
    for a in allowed:
        for scaled in (a, a * 100, a / 100):
            if abs(_round_half_up(scaled, decimals) - value) < 1e-9:
                return True
    return False


def pack_numbers(pack: Mapping[str, Any]) -> list[float]:
    values: set[float] = set()
    for item in pack["items"]:
        values.update(v for _t, v, _d in extract_numbers(item["text"]))
    values.update(v for _t, v, _d in extract_numbers(str(pack.get("date") or "")))
    return sorted(values)


def guard_text(text: str, allowed: Sequence[float]) -> tuple[str, list[dict[str, Any]]]:
    """Keep the sentences whose numbers are all in the pack and that do not read as advice."""

    kept, removed = [], []
    for sentence in (s.strip() for s in _SENTENCE.split(text) if s.strip()):
        bad = [token for token, value, decimals in extract_numbers(sentence) if not number_allowed(value, decimals, allowed)]
        if bad:
            removed.append({"text": sentence, "reason": "증거 팩에 없는 숫자", "numbers": bad})
        elif _ADVICE.search(sentence):
            removed.append({"text": sentence, "reason": "거래 권유 또는 방향 단정으로 읽히는 표현", "numbers": []})
        else:
            kept.append(sentence)
    return " ".join(kept), removed


def guard_sections(sections: Mapping[str, list[dict[str, Any]]], allowed: Sequence[float]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    removed: list[dict[str, Any]] = []
    out: dict[str, list[dict[str, Any]]] = {}
    for key, items in sections.items():
        out[key] = []
        for item in items:
            text, gone = guard_text(item["text"], allowed)
            removed.extend({**g, "section": key} for g in gone)
            if text:
                out[key].append({**item, "text": text})
    return out, removed


# --------------------------------------------------------------------------
# models, prices, budget
# --------------------------------------------------------------------------
@dataclass
class LLMReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Participant:
    role: str                              # analyst | critic | verifier
    provider: str
    model: str
    call: Callable[[str, str], LLMReply]   # (system, user) -> reply

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"


def prices() -> dict[str, tuple[float, float]]:
    table = dict(DEFAULT_PRICES)
    raw = os.getenv("GOLDLAB_REVIEW_PRICES")
    if raw:
        try:
            table.update({k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()})
        except (ValueError, TypeError, KeyError, IndexError):
            pass
    return table


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = prices().get(model, FALLBACK_PRICE)
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 6)


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """A hard cap in USD for one day across both symbols. ``spent`` starts at what earlier runs used."""

    def __init__(self, max_usd: float, spent: float = 0.0):
        self.max_usd, self.spent = float(max_usd), float(spent)

    @property
    def remaining(self) -> float:
        return self.max_usd - self.spent

    def reserve(self, estimate: float) -> None:
        if estimate > self.remaining:
            raise BudgetExceeded(f"예상 비용 {estimate:.3f}달러가 남은 예산 {self.remaining:.3f}달러를 넘습니다")

    def charge(self, cost: float) -> None:
        self.spent += cost


def default_budget_usd() -> float:
    try:
        return float(os.getenv("GOLDLAB_REVIEW_MAX_USD", "0.60"))
    except ValueError:
        return 0.60


def _spec(env: str, default: str) -> tuple[str, str]:
    raw = os.getenv(env) or default
    provider, _, model = raw.partition(":")
    return provider.strip(), model.strip()


def build_participants() -> dict[str, Participant]:
    """The three real models. A client is built on its first call, so a missing key fails that turn only."""

    out = {}
    for role, env, default, max_tokens in (
        ("analyst", "GOLDLAB_REVIEW_ANALYST", DEFAULT_ANALYST, 12000),
        ("critic", "GOLDLAB_REVIEW_CRITIC", DEFAULT_CRITIC, 6000),
        ("verifier", "GOLDLAB_REVIEW_VERIFIER", DEFAULT_VERIFIER, 6000),
    ):
        provider, model = _spec(env, default)
        out[role] = Participant(role, provider, model, _lazy_chat(provider, model, max_tokens))
    return out


def _lazy_chat(provider: str, model: str, max_tokens: int) -> Callable[[str, str], LLMReply]:
    state: dict[str, Any] = {}

    def call(system: str, user: str) -> LLMReply:
        if "llm" not in state:
            from tradingagents.llm_clients import create_llm_client

            kwargs: dict[str, Any] = {"timeout": 240, "max_retries": 1}
            if provider == "anthropic":
                kwargs["max_tokens"] = max_tokens
            elif provider == "openai":
                kwargs["reasoning_effort"] = os.getenv("GOLDLAB_REVIEW_OPENAI_EFFORT", "low")
            elif provider == "google":
                kwargs["thinking_level"] = os.getenv("GOLDLAB_REVIEW_GOOGLE_THINKING", "low")
            state["llm"] = create_llm_client(provider, model, **kwargs).get_llm()
        from langchain_core.messages import HumanMessage, SystemMessage

        response = state["llm"].invoke([SystemMessage(content=system), HumanMessage(content=user)])
        usage = getattr(response, "usage_metadata", None) or {}
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        return LLMReply(str(content), int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))

    return call


# --------------------------------------------------------------------------
# prompts (Korean)
# --------------------------------------------------------------------------
SYSTEM_COMMON = """당신은 금·나스닥 선물 패턴 연구소(Gold Lab)의 '복기 노트' 팀 일원입니다. 이 노트는 연구소가 지난 거래일에 기록한 신호가 어떻게 됐는지 돌아보는 복기 도구이며, 신호를 만드는 도구가 아닙니다.

반드시 지킬 것
1. 숫자는 '증거 팩'에 적힌 것만 씁니다. 증거 팩에 없는 숫자를 만들거나, 더하고 빼서 새 숫자를 내지 마세요. 합계·평균·차이도 직접 계산하지 말고 팩의 숫자를 그대로 인용합니다. 나중에 코드가 노트의 모든 숫자를 팩과 대조해, 팩에 없는 숫자가 든 문장을 지웁니다.
2. 모든 문장에는 근거가 되는 증거 번호를 evidence 배열에 적습니다 (예: ["E3","E7"]). 번호가 없는 주장은 쓰지 않습니다.
3. 매수·매도·진입·청산·비중 같은 거래 권유, 가격 예측, '오를 것/내릴 것' 같은 방향 단정은 쓰지 않습니다. '내일 볼 것'은 예정된 지표나 확인할 기록 같은 관찰 포인트만 적습니다.
4. 연구 배경: 이 연구소의 10년 기록에서 단일 패턴도 닮은 차트 방식도 비용을 빼면 일관된 방향성 우위가 확인되지 않았습니다 (증거 팩의 연구 항목 참조). 그러니 하루의 맞음/틀림을 '패턴이 통했다/안 통했다'로 과대 해석하지 말고, 표본이 작으면 작다고 말합니다. 신호는 겹쳐서 뜨므로 건수만큼 독립된 정보가 아닙니다.
5. 한국어로, 쉬운 말과 짧은 문장으로 씁니다. 상승은 ▲, 하락은 ▼를 쓸 수 있습니다. 증거에 없는 원인(뉴스·심리)을 지어내지 않습니다. 모르면 '자료 없음'이라고 씁니다.
6. 출력은 JSON 객체 하나뿐입니다. 설명이나 마크다운 코드펜스를 붙이지 않습니다."""

ANALYST_DRAFT = """아래 증거 팩만 근거로 오늘의 복기 노트 초안을 JSON으로 쓰세요.

섹션 (각 섹션은 문장 객체의 배열, 한 문장 객체는 {{"text": "...", "evidence": ["E1", ...]}} 형식, 섹션당 1~3개, 문장 객체 하나에 문장은 최대 두 개, evidence는 문장당 최대 3개, 전체를 간결하게):
- summary: 오늘 장 요약 (가격 흐름, 세션별 특징)
- signals: 신호와 결과 (어떤 신호가 몇 건 떴고 4·12·24봉 뒤 맞음/틀림이 어땠는지, 채점 대기 포함)
- context: 상황별로 본 것 (세션·추세·변동성·지표 근접에 따라 결과가 어땠는지, 표본 수 명시)
- drift: 기록이 흔들리는 패턴 (최근 30일 기록이 10년 기록·당시 주장과 어긋난 곳, 표본 수 명시)
- watch: 내일 볼 것 (관찰 포인트만, 최대 3개, 예정 지표·확인할 기록)

출력 형식: {{"summary": [...], "signals": [...], "context": [...], "drift": [...], "watch": [...]}}

{pack}"""

CRITIC = """당신은 비판자입니다. 아래 초안을 증거 팩과 대조해 약점을 공격하세요: 과대 해석, 작은 표본, 미래 정보 사용(look-ahead), 생존 편향, 다른 설명 가능성, 빠진 맥락. 칭찬은 필요 없습니다.
또 오늘 기록에서 떠오른 '검증할 가설'을 최대 3개 제안하세요. 가설은 워크포워드 연구가 한 칸으로 검증할 수 있게 패턴·상황(세션/추세/변동성/지표 중 최대 하나)·봉 수로 정해진 문장이어야 합니다 (예: "패턴 X는 미국장에서 12봉 뒤 기준 승률보다 높다"). 가설도 숫자는 증거 팩의 것만 쓰고, 봉 수는 4, 12, 24, 72 중 하나입니다.
쓸 수 있는 패턴 이름(pattern): {patterns}
세션 값: us, europe, asia, off / 추세: up, down, range / 변동성: low, mid, high / 지표: near, far

출력 형식:
{{"challenges": [{{"type": "과대해석|작은표본|미래정보|생존편향|대안설명|누락맥락", "target": "공격하는 초안 문장의 앞부분", "text": "...", "evidence": ["E1"]}}],
 "hypotheses": [{{"text": "...", "pattern": "패턴 이름", "context": {{"session": "us"}}, "horizon": 12, "evidence": ["E1"]}}]}}
context는 없으면 {{}} 입니다.

{pack}

[초안]
{draft}"""

VERIFIER = """당신은 검증자입니다. 초안과 비판의 모든 숫자와 주장을 증거 팩과 한 줄씩 대조하세요. 숫자가 팩과 다르거나, 팩에 근거가 없거나, 근거로 단 증거 번호가 그 주장을 뒷받침하지 않거나, 방향이 틀리거나, 팩이 말하는 것보다 세게 말한 문장을 모두 찾습니다. 문제가 없는 문장은 적지 않습니다.

출력 형식:
{{"checked": 대조한 문장 수(정수),
 "problems": [{{"source": "draft|critique", "text": "문제 문장 그대로", "status": "unsupported|mismatch|overreach", "reason": "한 문장", "evidence": ["E1"]}}],
 "overall": "한 문장 총평"}}

{pack}

[초안]
{draft}

[비판]
{critique}"""

ANALYST_FINAL = """당신은 초안을 쓴 분석가입니다. 비판과 검증 결과를 받았습니다. 최종 노트를 JSON으로 다시 쓰세요.
- 검증자가 문제로 지적한 문장은 고치거나 지웁니다. 증거 팩에 근거가 없으면 지웁니다.
- 비판 중 타당한 것은 본문에 반영합니다 (표본이 작다, 겹치는 신호다 같은 한계를 분명히).
- 비판 중 끝까지 유효한데 본문으로 풀리지 않는 것은 dissent(이견)에 '비판자는 ...라고 지적했다' 형식으로 남깁니다 (1~3개). 비판이 모두 반영됐으면 dissent는 빈 배열입니다.
- 가설은 쓰지 않습니다 (코드가 따로 붙입니다). 섹션당 1~3개, 문장 객체 하나에 문장은 최대 두 개, evidence는 문장당 최대 3개로 간결하게 씁니다.
- 섹션 형식은 초안과 같습니다. 문장마다 evidence를 답니다 (dissent는 증거 번호가 없어도 되지만 숫자는 증거 팩의 것만).

출력 형식: {{"summary": [...], "signals": [...], "context": [...], "drift": [...], "watch": [...], "dissent": [...]}}

{pack}

[초안]
{draft}

[비판]
{critique}

[검증 결과]
{verification}"""


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def parse_json(text: str) -> dict[str, Any] | None:
    """The first JSON object in a model reply, tolerating a code fence or a preface."""

    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    for candidate in (body, body[body.find("{") : body.rfind("}") + 1] if "{" in body else ""):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def clean_statements(raw: Any, valid_ids: set[str], *, need_evidence: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Statements as {text, evidence}; invented evidence ids are dropped, and so are unsupported statements."""

    kept, dropped = [], []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"text": item, "evidence": []}
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cited = [str(e).strip() for e in (item.get("evidence") or []) if str(e).strip()]
        good = [e for e in dict.fromkeys(cited) if e in valid_ids]
        if need_evidence and not good:
            dropped.append({"text": text, "reason": "유효한 증거 번호가 없음", "numbers": []})
            continue
        kept.append({"text": text, "evidence": good})
    return kept, dropped


# --------------------------------------------------------------------------
# hypotheses
# --------------------------------------------------------------------------
HYPOTHESIS_HORIZONS = (4, 12, 24, 72)


def normalize_hypothesis(raw: Mapping[str, Any], index: int, registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The critic's hypothesis as a spec walkforward can test, or flagged as one it cannot."""

    if registry is None:
        from .patterns import PATTERN_REGISTRY as registry  # noqa: N811
    labels = {value[0]: name for name, value in registry.items()}
    pattern = str(raw.get("pattern") or "").strip()
    pattern = pattern if pattern in registry else labels.get(pattern, pattern)
    try:
        horizon = int(raw.get("horizon") or 0)
    except (TypeError, ValueError):
        horizon = 0
    context = {}
    for dim, value in (raw.get("context") or {}).items() if isinstance(raw.get("context"), Mapping) else []:
        value = SESSION_ALIASES.get(str(value).strip(), str(value).strip())
        dim = DIM_ALIASES.get(str(dim).strip().lower(), str(dim).strip())
        if value:
            context[dim] = value
    if raw.get("session"):
        context.setdefault("session", SESSION_ALIASES.get(str(raw["session"]).strip(), str(raw["session"]).strip()))
    problems = []
    if pattern not in registry:
        problems.append("알 수 없는 패턴")
    if horizon not in HYPOTHESIS_HORIZONS:
        problems.append("봉 수가 4·12·24·72가 아님")
    if len(context) > 1:
        problems.append("상황 조건이 둘 이상")
    for dim, value in context.items():
        if dim not in CONTEXT_VALUES or value not in CONTEXT_VALUES[dim]:
            problems.append(f"상황 조건 '{dim}={value}'을 표현할 수 없음")
    text = str(raw.get("text") or "").strip()
    lower = str(raw.get("direction") or "").lower() in ("lower", "below", "낮음") or bool(re.search(r"낮|못한|않", text))
    spec = {"pattern": pattern, "horizon": horizon, "context": context, "direction": "lower" if lower else "higher"}
    if not text:
        text = _hypothesis_text(spec, registry)
    else:
        text = _readable(text, pattern, context, registry)
    return {
        "id": f"H{index}",
        "text": text,
        "spec": spec,
        "expressible": not problems,
        "why_not": "; ".join(problems) or None,
        "status": "미검증",
        "result": None,
        "evidence": [str(e) for e in raw.get("evidence") or []][:4],
        "proposed_by": "critic",
    }


def _topic_particle(word: str) -> str:
    """은 after a final consonant, 는 after a vowel (Hangul syllables only; anything else gets 는)."""

    last = word.rstrip()[-1:]
    if "가" <= last <= "힣":
        return "은" if (ord(last) - ord("가")) % 28 else "는"
    return "는"


def _readable(text: str, pattern: str, context: Mapping[str, str], registry: Mapping[str, Any]) -> str:
    """The page shows Korean labels, not code names: doji(도지) becomes 도지, asia becomes 아시아장."""

    if pattern in registry:
        label = registry[pattern][0]
        text = re.sub(rf"{re.escape(label)}\s*\(\s*{re.escape(pattern)}\s*\)|{re.escape(pattern)}\s*\(\s*{re.escape(label)}\s*\)", label, text)
        text = re.sub(rf"(?<![A-Za-z_]){re.escape(pattern)}(?![A-Za-z_])", label, text)
        text = re.sub(rf"{re.escape(label)}\s*\(\s*{re.escape(label)}\s*\)", label, text)
        text = re.sub(rf"{re.escape(label)}(는|은)", lambda m: label + _topic_particle(label), text)
    names = {"session": SESSION_KO, "trend": TREND_KO, "vol": VOL_KO, "event": EVENT_KO}
    for dim, value in context.items():
        word = names.get(dim, {}).get(value)
        if word:
            text = re.sub(rf"(?<![A-Za-z_]){re.escape(value)}(?![A-Za-z_])", word, text)
    return text


def _hypothesis_text(spec: Mapping[str, Any], registry: Mapping[str, Any]) -> str:
    label = (registry.get(spec.get("pattern")) or (spec.get("pattern"),))[0]
    where = ", ".join(f"{dim}={value}" for dim, value in (spec.get("context") or {}).items())
    return f"패턴 {label}" + (f" ({where})" if where else "") + f"는 {spec.get('horizon')}봉 뒤 기준 승률보다 높다"


def evaluate_hypotheses(
    hypotheses: Sequence[dict[str, Any]],
    series: Any,
    *,
    family: int = 1,
    run_study: Callable[..., Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Run each expressible hypothesis through the walk-forward study on the stored history.

    One study run covers every pattern and horizon asked for. A hypothesis passes only if its
    cell has an independent-sample test, its raw p-value clears a Bonferroni cut over the whole
    family the hypotheses were drawn from (``family``, the stored study's tested cells), and the
    shrunk edge is positive. The history is the same history the critic's idea came from, so a pass
    is a reason to look harder, not a finding.
    """

    if run_study is None:
        from .walkforward import run_walkforward_study as run_study  # noqa: N806
    todo = [h for h in hypotheses if h.get("expressible") and h.get("status") == "미검증"]
    if not todo:
        return []
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    study = run_study(
        series,
        horizons=sorted({int(h["spec"]["horizon"]) for h in todo}),
        patterns=sorted({h["spec"]["pattern"] for h in todo}),
        with_legacy=False,
    )
    alpha = 0.05 / max(1, int(family))
    changed = []
    for h in todo:
        spec = h["spec"]
        row = next((r for r in study.get("patterns") or [] if r.get("pattern") == spec["pattern"]), None)
        cell = (row or {}).get("horizons", {}).get(str(spec["horizon"])) or {}
        if spec["context"]:
            (dim, value), = spec["context"].items()
            cell = ((cell.get("context") or {}).get(dim) or {}).get(value) or {}
        n = int(cell.get("count") or 0)
        p = cell.get("p_value")
        edge = cell.get("shrunk_edge_win_rate")
        if not n or p is None:
            status, why = "표본 부족", "독립 표본이 모자라 검정하지 못함"
        elif p < alpha and (((cell.get("win_rate") or 0) < (cell.get("base_win_rate") or 0)) if spec.get("direction") == "lower" else (edge or 0) > 0):
            status, why = "통과", f"p값이 보정 기준 {alpha:.2e}보다 작고 승률이 기준보다 " + ("낮음" if spec.get("direction") == "lower" else "높음")
        else:
            status, why = "기각", f"p값이 보정 기준 {alpha:.2e}를 넘거나 보정 승률이 기준 이하"
        h["status"] = status
        h["result"] = {
            "tested_at": stamp, "n": n, "win_rate": cell.get("win_rate"), "base_win_rate": cell.get("base_win_rate"),
            "shrunk_edge_win_rate": edge, "p_value": p, "independent_n": cell.get("independent_count"),
            "alpha": alpha, "family": int(family), "reason": why, "history_end": study.get("end"),
            "caveat": "가설이 나온 기록과 같은 10년 기록으로 검증해 낙관적일 수 있음",
        }
        changed.append(h)
    return changed


# --------------------------------------------------------------------------
# the debate
# --------------------------------------------------------------------------
RETRIES = 1            # one more try after a transient provider error (503, timeout)
RETRY_DELAY = 3.0
ROLE_LABELS = {"analyst_draft": "분석가 초안", "critic": "비판", "verifier": "검증", "analyst_final": "분석가 최종"}


def _turn(role: str, who: Participant, system: str, user: str, budget: Budget, *, max_out: int = 5500) -> dict[str, Any]:
    """One model call as a transcript entry. Never raises: a failure is a turn with ``ok`` false."""

    turn: dict[str, Any] = {"turn": role, "label": ROLE_LABELS[role], "provider": who.provider, "model": who.model, "ok": False, "error": None, "output": None, "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}}
    pin, pout = prices().get(who.model, FALLBACK_PRICE)
    estimate = ((len(system) + len(user)) / 1.2 * pin + max_out * pout) / 1_000_000
    try:
        budget.reserve(estimate)
    except BudgetExceeded as exc:
        turn["error"] = f"예산: {exc}"
        turn["skipped"] = True
        return turn
    reply = None
    for attempt in range(RETRIES + 1):
        try:
            reply = who.call(system, user)
            turn["error"] = None
            break
        except Exception as exc:  # noqa: BLE001 - a provider failure must not stop the note
            turn["error"] = f"{exc.__class__.__name__}: {str(exc)[:200]}"
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY)
    if reply is None:
        return turn
    cost = cost_of(who.model, reply.input_tokens, reply.output_tokens)
    budget.charge(cost)
    turn["usage"] = {"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens, "cost_usd": cost}
    parsed = parse_json(reply.text)
    if parsed is None:
        turn["error"] = "JSON으로 읽을 수 없는 응답"
        turn["raw"] = reply.text[:1500]
        return turn
    turn["ok"], turn["output"] = True, parsed
    return turn


def run_debate(pack: Mapping[str, Any], people: Mapping[str, Participant], budget: Budget) -> dict[str, Any]:
    """Four turns, in order: analyst draft, critic, verifier, analyst final. Failures degrade, never stop."""

    ids = pack_ids(pack)
    text = pack_text(pack)
    turns: list[dict[str, Any]] = []
    degraded: list[str] = []
    dropped: list[dict[str, Any]] = []

    def statements(output: Mapping[str, Any], keys: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        sections = {}
        for key in keys:
            kept, gone = clean_statements(output.get(key), ids, need_evidence=key != "dissent")
            sections[key] = kept
            dropped.extend({**g, "section": key} for g in gone)
        return sections

    # a. analyst draft
    draft_turn = _turn("analyst_draft", people["analyst"], SYSTEM_COMMON, ANALYST_DRAFT.format(pack=text), budget)
    turns.append(draft_turn)
    if not draft_turn["ok"]:
        return {"ok": False, "turns": turns, "degraded": ["분석가 초안 실패"], "sections": {}, "hypotheses": [], "problems": [], "dropped": dropped}
    draft = statements(draft_turn["output"], DRAFT_KEYS)
    draft_json = _compact_json(draft)

    # b. critic
    from .patterns import PATTERN_REGISTRY

    patterns = ", ".join(f"{name}({value[0]})" for name, value in PATTERN_REGISTRY.items())
    critic_turn = _turn("critic", people["critic"], SYSTEM_COMMON, CRITIC.format(pack=text, draft=draft_json, patterns=patterns), budget)
    turns.append(critic_turn)
    critique: dict[str, Any] = {"challenges": [], "hypotheses": []}
    hypotheses: list[dict[str, Any]] = []
    if critic_turn["ok"]:
        out = critic_turn["output"]
        challenges, gone = clean_statements([{"text": f"[{c.get('type', '')}] {c.get('text', '')}", "evidence": c.get("evidence")} for c in out.get("challenges") or [] if isinstance(c, Mapping)], ids, need_evidence=False)
        critique["challenges"] = challenges
        for raw in (out.get("hypotheses") or [])[:3]:
            if isinstance(raw, Mapping):
                hypotheses.append(normalize_hypothesis(raw, len(hypotheses) + 1))
        critique["hypotheses"] = [{"text": h["text"], "spec": h["spec"]} for h in hypotheses]
    else:
        degraded.append("비판 생략")

    # c. verifier
    verify_turn = _turn("verifier", people["verifier"], SYSTEM_COMMON, VERIFIER.format(pack=text, draft=draft_json, critique=_compact_json(critique)), budget)
    turns.append(verify_turn)
    problems: list[dict[str, Any]] = []
    if verify_turn["ok"]:
        for p in verify_turn["output"].get("problems") or []:
            if isinstance(p, Mapping) and p.get("text"):
                problems.append({"source": str(p.get("source") or ""), "text": str(p["text"]), "status": str(p.get("status") or ""), "reason": str(p.get("reason") or ""), "evidence": [str(e) for e in p.get("evidence") or []]})
    else:
        degraded.append("검증 생략")

    # d. analyst final
    verification = _compact_json({"problems": problems, "overall": (verify_turn["output"] or {}).get("overall") if verify_turn["ok"] else "검증 생략"})
    final_turn = _turn("analyst_final", people["analyst"], SYSTEM_COMMON, ANALYST_FINAL.format(pack=text, draft=draft_json, critique=_compact_json(critique), verification=verification), budget)
    turns.append(final_turn)
    if final_turn["ok"]:
        sections = statements(final_turn["output"], DRAFT_KEYS + ("dissent",))
    else:
        degraded.append("최종 재작성 실패: 초안을 검증 지적만 반영해 사용")
        sections = _without_flagged(draft, problems)
        sections["dissent"] = [{"text": c["text"], "evidence": c["evidence"]} for c in critique["challenges"][:2]]
    return {"ok": True, "turns": turns, "degraded": degraded, "sections": sections, "hypotheses": hypotheses, "problems": problems, "dropped": dropped}


def _without_flagged(sections: Mapping[str, list[dict[str, Any]]], problems: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    flagged = [re.sub(r"\s+", "", p["text"]) for p in problems if p.get("source") != "critique" and p.get("text")]
    out = {}
    for key, items in sections.items():
        out[key] = [i for i in items if not any(f and (f in re.sub(r"\s+", "", i["text"]) or re.sub(r"\s+", "", i["text"]) in f) for f in flagged)]
    return out


# --------------------------------------------------------------------------
# assembling the note
# --------------------------------------------------------------------------
def render_text(symbol: str, day: str, mode_line: str, sections: Mapping[str, list[dict[str, Any]]], hypotheses: Sequence[Mapping[str, Any]]) -> str:
    lines = [f"{symbol} AI 복기 노트 · {day} (KST)", mode_line, ""]
    for key, title in SECTIONS:
        lines.append(f"■ {title}")
        if key == "hypotheses":
            lines.extend(f"- {h['id']} [{h['status']}] {h['text']}" for h in hypotheses) if hypotheses else lines.append("- 제안된 가설 없음")
        else:
            items = sections.get(key) or []
            if not items:
                lines.append("- 이견 없음" if key == "dissent" else "- 근거가 확인된 내용이 없어 비웠습니다")
            for item in items:
                tag = f" [{', '.join(item['evidence'])}]" if item.get("evidence") else ""
                lines.append(f"- {item['text']}{tag}")
        lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines)


def assemble_note(symbol: str, day: str, pack: Mapping[str, Any], debate: Mapping[str, Any], *, people: Mapping[str, Participant], now: datetime, run_day: str, attempts: int = 1) -> dict[str, Any]:
    """Guard the debate's output and make the stored record."""

    allowed = pack_numbers(pack)
    sections, removed = guard_sections(debate["sections"], allowed)
    removed = list(debate.get("dropped") or []) + removed
    hypotheses = []
    for h in debate.get("hypotheses") or []:
        text, gone = guard_text(h["text"], allowed)
        removed.extend({**g, "section": "hypotheses"} for g in gone)
        hypotheses.append({**h, "text": text or _hypothesis_text(h["spec"], _registry())})
    degraded = list(debate.get("degraded") or [])
    critic = next((t for t in debate["turns"] if t["turn"] == "critic"), None)
    solo = critic is None or not critic["ok"]
    mode = "solo" if solo else "debate"
    mode_line = "작성 방식: 단독 작성 (" + ", ".join(degraded or ["비판 없음"]) + ")" if solo else "작성 방식: 3자 토론" + (f" (일부 생략: {', '.join(degraded)})" if degraded else "")
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "by_model": {}}
    for t in debate["turns"]:
        u = t["usage"]
        usage["input_tokens"] += u["input_tokens"]
        usage["output_tokens"] += u["output_tokens"]
        usage["cost_usd"] = round(usage["cost_usd"] + u["cost_usd"], 6)
        row = usage["by_model"].setdefault(f"{t['provider']}:{t['model']}", {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        row["input_tokens"] += u["input_tokens"]
        row["output_tokens"] += u["output_tokens"]
        row["cost_usd"] = round(row["cost_usd"] + u["cost_usd"], 6)
    return {
        "version": 1,
        "status": "ok",
        "symbol": symbol,
        "date": day,
        "mode": mode,
        "mode_line": mode_line,
        "degraded": degraded,
        "generated_at": now.isoformat(),
        "run_day": run_day,
        "attempts": attempts,
        "window": pack["window"],
        "models": {role: p.name for role, p in people.items()},
        "sections": {key: sections.get(key, []) for key, _t in SECTIONS if key != "hypotheses"},
        "hypotheses": hypotheses,
        "verifier_problems": debate.get("problems") or [],
        "guard": {"removed": removed, "numbers_known": len(allowed)},
        "debate": {"turns": debate["turns"]},
        "usage": usage,
        "evidence": {"items": pack["items"], "keys": pack["keys"], "bars": pack["bars"], "signals": pack["signals"]},
        "text": render_text(symbol, day, mode_line, sections, hypotheses),
        "footer": FOOTER,
    }


def _registry() -> Mapping[str, Any]:
    from .patterns import PATTERN_REGISTRY

    return PATTERN_REGISTRY


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def save_record(repo: Any, record: Mapping[str, Any]) -> str:
    """One row per (symbol, day), replaced in place."""

    day = str(record["date"])
    return repo.save_backtest_run(
        {
            "start_date": day,
            "end_date": day,
            "universe_size": int((record.get("evidence") or {}).get("bars") or 0),
            "metrics": {"review": dict(record), "trade_count": 0},
            "config": {"symbol": record["symbol"], "date": day, "status": record.get("status"), "mode": record.get("mode"), "models": record.get("models")},
            "equity_curve": [],
            "trades": [],
            "notes": ["research review only: not a forecast and not trading advice"],
        },
        label=review_label(record["symbol"], day),
        keep_latest=True,
    )


def _record_of(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    value = ((row or {}).get("metrics_json") or {}).get("review")
    return dict(value) if isinstance(value, Mapping) else None


def load_record(repo: Any, symbol: str, day: date | str) -> dict[str, Any] | None:
    if repo is None:
        return None
    try:
        return _record_of(repo.latest_backtest_run(label=review_label(symbol, day)))
    except Exception:  # noqa: BLE001
        return None


def list_records(repo: Any, symbol: str | None = None, *, limit: int = 30, newest: str = "label") -> list[dict[str, Any]]:
    prefix = f"{LABEL_PREFIX}:{symbol}:" if symbol else f"{LABEL_PREFIX}:"
    try:
        rows = repo.list_backtest_runs(prefix, limit=limit, newest=newest)
    except Exception:  # noqa: BLE001
        return []
    return [r for r in (_record_of(row) for row in rows) if r]


def spent_on(repo: Any, run_day: str) -> float:
    """What the reviews written on one KST day cost, both symbols, failed attempts included."""

    return round(sum(float((r.get("usage") or {}).get("cost_usd") or 0) for r in list_records(repo, None, limit=200, newest="created") if r.get("run_day") == run_day), 6)


def page_payload(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """What the chart page needs: the note, its debate, the evidence it cites. Not the raw replies."""

    if not record or record.get("status") != "ok":
        return None
    turns = []
    for t in (record.get("debate") or {}).get("turns") or []:
        turns.append({k: t.get(k) for k in ("turn", "label", "provider", "model", "ok", "error", "output", "usage")})
    return {
        "symbol": record["symbol"],
        "date": record["date"],
        "mode": record.get("mode"),
        "mode_line": record.get("mode_line"),
        "generated_at": record.get("generated_at"),
        "models": record.get("models"),
        "sections": record.get("sections"),
        "hypotheses": record.get("hypotheses") or [],
        "verifier_problems": record.get("verifier_problems") or [],
        "guard_removed": (record.get("guard") or {}).get("removed") or [],
        "turns": turns,
        "usage": {"cost_usd": (record.get("usage") or {}).get("cost_usd"), "input_tokens": (record.get("usage") or {}).get("input_tokens"), "output_tokens": (record.get("usage") or {}).get("output_tokens")},
        "evidence": {item["id"]: item["text"] for item in (record.get("evidence") or {}).get("items") or []},
        "footer": record.get("footer") or FOOTER,
    }


def load_stored_review(repo: Any, symbol: str) -> dict[str, Any] | None:
    """The newest finished note for the page, or None."""

    if repo is None:
        return None
    for record in list_records(repo, symbol, limit=6):
        if record.get("status") == "ok":
            return page_payload(record)
    return None


# --------------------------------------------------------------------------
# running it
# --------------------------------------------------------------------------
def _study(repo: Any, symbol: str, interval: str) -> dict[str, Any] | None:
    try:
        row = repo.latest_backtest_run(label=f"gold:{symbol}:{interval}")
    except Exception:  # noqa: BLE001
        return None
    value = ((row or {}).get("metrics_json") or {}).get("study")
    return dict(value) if isinstance(value, Mapping) else None


def load_recent_bars(repo: Any, symbol: str, since: datetime) -> list[Bar]:
    rows = []
    if repo is not None:
        try:
            rows = repo.goldlab_load_bars(symbol, REVIEW_INTERVAL, since=since)
        except Exception:  # noqa: BLE001
            rows = []
    if rows:
        aware = lambda t: t if t.tzinfo else t.replace(tzinfo=timezone.utc)  # noqa: E731 - sqlite drops the zone
        return [Bar(timestamp=aware(r["ts"]), open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r["volume"], source=r.get("source") or "yahoo") for r in rows]
    from .barstore import read_cache

    cached = read_cache(symbol, REVIEW_INTERVAL)
    return [b for b in (cached.bars if cached else ()) if b.timestamp >= since]


def run_review(
    symbol: str,
    *,
    repo: Any,
    people: Mapping[str, Participant] | None = None,
    now: datetime | None = None,
    day: date | None = None,
    force: bool = False,
    max_usd: float | None = None,
    bars: Sequence[Bar] | None = None,
    signals: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write today's note for one symbol if it does not exist yet. Idempotent and never raises on a provider."""

    now = now or datetime.now(timezone.utc)
    run_day = now.astimezone(KST).date().isoformat()
    if bars is None:
        bars = load_recent_bars(repo, symbol, window_for((day or latest_review_day(now)) - timedelta(days=0 if day else 6))[0])
    if day is None:
        day = pick_review_day(bars, now)
        if day is None:
            return {"status": "no_data", "symbol": symbol, "detail": "최근 거래일 구간에 봉이 없음"}
    existing = load_record(repo, symbol, day)
    attempts = int((existing or {}).get("attempts") or 0)
    if existing and not force:
        if existing.get("status") == "ok":
            return {"status": "exists", "symbol": symbol, "date": str(day), "cost_usd": (existing.get("usage") or {}).get("cost_usd")}
        if attempts >= MAX_ATTEMPTS:
            return {"status": "gave_up", "symbol": symbol, "date": str(day), "attempts": attempts}

    budget = Budget(max_usd if max_usd is not None else default_budget_usd(), spent_on(repo, run_day))
    if budget.remaining <= 0:
        return {"status": "budget", "symbol": symbol, "date": str(day), "spent_usd": budget.spent, "max_usd": budget.max_usd}

    if signals is None:
        from .ledger import open_ledger

        signals = open_ledger(symbol, REVIEW_INTERVAL, repo=repo).all()
    from .analogs import load_stored_analogs

    pack = build_evidence(
        symbol, day, bars=bars, signals=signals, study=_study(repo, symbol, "5m"), study_1h=_study(repo, symbol, "1h"),
        analogs=load_stored_analogs(repo, symbol, "5m"), now=now,
    )
    people = people or build_participants()
    debate = run_debate(pack, people, budget)
    if not debate["ok"]:
        record = {
            "version": 1, "status": "failed", "symbol": symbol, "date": str(day), "run_day": run_day, "attempts": attempts + 1,
            "generated_at": now.isoformat(), "degraded": debate["degraded"], "debate": {"turns": debate["turns"]},
            "usage": {"cost_usd": round(sum(t["usage"]["cost_usd"] for t in debate["turns"]), 6), "input_tokens": sum(t["usage"]["input_tokens"] for t in debate["turns"]), "output_tokens": sum(t["usage"]["output_tokens"] for t in debate["turns"])},
            "evidence": {"items": pack["items"], "keys": pack["keys"], "bars": pack["bars"], "signals": pack["signals"]},
        }
        save_record(repo, record)
        return {"status": "failed", "symbol": symbol, "date": str(day), "error": debate["turns"][-1].get("error"), "cost_usd": record["usage"]["cost_usd"], "attempts": attempts + 1}
    record = assemble_note(symbol, str(day), pack, debate, people=people, now=now, run_day=run_day, attempts=attempts + 1)
    save_record(repo, record)
    return {
        "status": "ok", "symbol": symbol, "date": str(day), "mode": record["mode"], "degraded": record["degraded"],
        "cost_usd": record["usage"]["cost_usd"], "removed": len(record["guard"]["removed"]), "hypotheses": len(record["hypotheses"]),
    }


# --------------------------------------------------------------------------
# the weekly hypothesis job
# --------------------------------------------------------------------------
WEEKLY_DAYS = 6.5


def weekly_marker_label(symbol: str) -> str:
    return f"{LABEL_PREFIX}:weekly:{symbol}"


def run_weekly_hypotheses(
    symbol: str,
    *,
    repo: Any,
    series: Any = None,
    run_study: Callable[..., Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    if_due: bool = True,
) -> dict[str, Any]:
    """Test every untested, expressible hypothesis of the last 60 days; at most once a week with ``if_due``."""

    now = now or datetime.now(timezone.utc)
    if if_due:
        try:
            marker = repo.latest_backtest_run(label=weekly_marker_label(symbol))
        except Exception:  # noqa: BLE001
            marker = None
        ran = ((marker or {}).get("metrics_json") or {}).get("ran_at")
        if ran and now - datetime.fromisoformat(ran) < timedelta(days=WEEKLY_DAYS):
            return {"status": "not_due", "symbol": symbol, "last_run": ran}
    records = [r for r in list_records(repo, symbol, limit=60) if r.get("status") == "ok"]
    pending = [(r, h) for r in records for h in r.get("hypotheses") or [] if h.get("expressible") and h.get("status") == "미검증"]
    if not pending:
        return {"status": "nothing_to_test", "symbol": symbol}
    if series is None:
        from .barstore import load_history

        series = load_history(symbol, REVIEW_INTERVAL, repo=None)
        if series is None or not len(series):
            return {"status": "no_history", "symbol": symbol}
    family = int(((_study(repo, symbol, "5m") or {}).get("fdr") or {}).get("tested") or 1)
    changed = evaluate_hypotheses([h for _r, h in pending], series, family=family, run_study=run_study, now=now)
    for record in {id(r): r for r, _h in pending}.values():
        save_record(repo, record)
    repo.save_backtest_run(
        {"start_date": str(now.date()), "end_date": str(now.date()), "metrics": {"ran_at": now.isoformat(), "tested": len(changed), "trade_count": 0}, "config": {"symbol": symbol}, "notes": []},
        label=weekly_marker_label(symbol), keep_latest=True,
    )
    return {"status": "ok", "symbol": symbol, "tested": len(changed), "results": {h["id"]: h["status"] for h in changed}}

"""Which story the channel tells today.

A daily channel does not survive on one format. Most trading days nothing
happens: the account moves a third of a percent, nothing is closed, the same
names sit in the book. Posting "nothing happened today" on those days does not
just waste a slot, it teaches the feed that the channel is not worth showing.

So the schedule does not pick the story, the data does. Every story carries the
condition that fires it and a score, and the day's video is whichever fired
strongest. When nothing fires there is standby material that needs no data at
all, which is the only honest way to hold a daily slot through a quiet week.

The score is novelty times magnitude times completeness. Novelty asks whether
this story ran recently, magnitude asks how extreme its number is, and
completeness asks whether it has a beginning and an end inside thirty seconds.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
LEDGER_ENV = "TRADINGAGENTS_SHORTS_LEDGER"
DEFAULT_LEDGER = Path("shorts-out/published.json")

# A weekly curve needs enough days to have a shape.
MIN_CURVE_DAYS = 5

MILESTONES = (10, 25, 50, 100, 200, 365)


@dataclass(frozen=True)
class Story:
    """One thing the channel knows how to say, and when it is worth saying."""

    key: str
    label: str
    tier: str                 # daily | event | periodic | standby
    completeness: float       # how self-contained the cut is, 0..1
    cooldown_days: int        # how long before it may run again
    renderer: str | None      # the cut that draws it, or None while unbuilt

    @property
    def renderable(self) -> bool:
        return self.renderer is not None


STORIES: tuple[Story, ...] = (
    # --- always available on a trading day ---------------------------------
    # it has its own cut now, not the record cut with a picks title on it
    Story("picks", "오늘의 픽", "daily", 0.85, 2, "picks"),
    Story("record", "지금까지의 성적", "daily", 1.0, 7, "record"),
    # Why a name was chosen, which is the only question a new viewer has. It
    # outranks the record cut on purpose: a channel that only ever reports its
    # own losses gives nobody a reason to subscribe.
    Story("funnel", "349종목에서 오늘의 종목까지", "daily", 1.0, 4, "funnel"),
    # --- fired by something that actually happened -------------------------
    Story("exits", "오늘 정리된 종목", "event", 0.95, 1, "record"),
    Story("stop_worked", "손절이 작동한 날", "event", 1.0, 5, "record"),
    Story("take_profit", "목표가에 닿았다", "event", 1.0, 2, None),
    Story("crossover", "AI와 규칙이 뒤집혔다", "event", 0.9, 7, None),
    Story("equity_extreme", "계좌 신고가·신저가", "event", 0.85, 5, None),
    Story("big_mover", "한 종목이 계좌를 흔들었다", "event", 0.95, 3, "candles"),
    Story("rejected", "거른 종목의 그 뒤", "event", 1.0, 4, None),
    Story("debate", "강세 AI vs 약세 AI", "event", 1.0, 2, "debate"),
    Story("milestone", "이정표", "event", 1.0, 30, None),
    # --- the calendar ------------------------------------------------------
    Story("weekly", "주간 성적표", "periodic", 1.0, 6, "curve"),
    Story("monthly", "월간 결산", "periodic", 1.0, 25, None),
    # --- needs no data at all, which is what quiet days are for -------------
    Story("explain_stop", "손절선은 어떻게 정하나", "standby", 1.0, 14, "explain"),
    Story("explain_debate", "AI 토론은 뭘 보고 판단하나", "standby", 1.0, 14, "explain"),
    Story("explain_open", "왜 틀린 것까지 올리나", "standby", 1.0, 14, "explain"),
)
BY_KEY = {story.key: story for story in STORIES}


@dataclass
class Candidate:
    story: Story
    magnitude: float
    reason: str
    novelty: float = 1.0
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        return round(self.novelty * self.magnitude * self.story.completeness, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.story.key,
            "label": self.story.label,
            "tier": self.story.tier,
            "renderer": self.story.renderer,
            "renderable": self.story.renderable,
            "score": self.score,
            "novelty": round(self.novelty, 3),
            "magnitude": round(self.magnitude, 3),
            "reason": self.reason,
            "detail": self.detail,
        }


# ------------------------------------------------------------------ ledger
def ledger_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    raw = (os.getenv(LEDGER_ENV) or "").strip()
    return Path(raw) if raw else DEFAULT_LEDGER


def read_ledger(path: Path | None = None) -> list[dict[str, Any]]:
    target = ledger_path(path)
    if not target.exists():
        return []
    try:
        rows = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def record_published(key: str, *, video_id: str | None = None, when: date | None = None, path: Path | None = None, **extra: Any) -> dict[str, Any]:
    """Append what went out, so novelty can be judged tomorrow."""

    target = ledger_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = read_ledger(target)
    row = {"story": key, "date": (when or _today()).isoformat(), "video_id": video_id, **extra}
    rows.append(row)
    target.write_text(json.dumps(rows[-400:], ensure_ascii=False, indent=1), encoding="utf-8")
    return row


def _today(now: datetime | None = None) -> date:
    return (now or datetime.now(KST)).astimezone(KST).date()


def _novelty(story: Story, ledger: Sequence[Mapping[str, Any]], today: date) -> float:
    """How new this is: full for something never told, climbing back after.

    Snapping straight back to 1.0 the day a cooldown lapses is what made the
    channel repetitive even with the shelf full — the single strongest story
    simply alternated with itself every other slot. Past the cooldown novelty
    keeps climbing, so a story that ran a week ago still loses to one that has
    not run in three, and the whole shelf gets used.
    """

    last: date | None = None
    for row in ledger:
        if str(row.get("story")) != story.key:
            continue
        try:
            when = date.fromisoformat(str(row.get("date"))[:10])
        except ValueError:
            continue
        if last is None or when > last:
            last = when
    if last is None:
        return 1.0                                      # never told: it goes first
    days = (today - last).days
    cooldown = max(story.cooldown_days, 1)
    if days < cooldown:
        return round(max(0.0, days / cooldown) * 0.6, 3)
    rested = min((days - cooldown) / (cooldown * 2), 1.0)
    return round(0.75 + 0.25 * rested, 3)


# -------------------------------------------------------------- triggers
def _closed(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in payload.get("closed") or [] if item.get("realized_return") is not None]


def _books(payload: Mapping[str, Any]) -> dict[str, float]:
    return {
        str(item.get("key")): float((item.get("summary") or {}).get("total_return") or 0.0)
        for item in payload.get("accounts") or []
        if (item.get("summary") or {}).get("total_return") is not None
    }


def evaluate(payload: Mapping[str, Any], *, now: datetime | None = None, ledger: Sequence[Mapping[str, Any]] | None = None) -> list[Candidate]:
    """Every story that fired today, strongest first."""

    today = _today(now)
    history = list(ledger if ledger is not None else read_ledger())
    summary = payload.get("summary") or {}
    closed = _closed(payload)
    positions = list(payload.get("positions") or [])
    books = _books(payload)
    found: list[Candidate] = []

    def add(key: str, magnitude: float, reason: str, **detail: Any) -> None:
        story = BY_KEY.get(key)
        if story is None:
            return
        found.append(Candidate(story, max(0.0, min(magnitude, 1.0)), reason, _novelty(story, history, today), detail))

    # --- daily -------------------------------------------------------------
    today_entries = [item for item in positions if str(item.get("entry_date"))[:10] == today.isoformat()]
    if today_entries:
        add("picks", 0.45 + min(len(today_entries), 4) * 0.05,
            f"오늘 {len(today_entries)}종목을 새로 담았습니다.", count=len(today_entries))

    closed_count = int(summary.get("closed_count") or len(closed))
    if closed_count >= 3:
        add("record", min(0.4 + closed_count * 0.03, 0.7),
            f"정리된 거래가 {closed_count}건 쌓였습니다.", closed=closed_count)

    # The screen itself, which needs a run that actually threw something away.
    funnel = payload.get("funnel") or {}
    universe = int(funnel.get("universe") or 0)
    stages = list(funnel.get("stages") or [])
    survived = int(stages[-1].get("to") or 0) if stages else 0
    # Two stages is a funnel: on a rules-only run the screen does its work in
    # one pass (349 → 20) and the ranking does the rest (20 → 3). Asking for
    # three kept it off the air on every day the harness actually ran.
    if universe >= 50 and len(stages) >= 2 and survived:
        # the harder the cut, the better the story: 349 → 7 is worth watching,
        # 60 → 55 is a formality
        severity = 1.0 - (survived / universe)
        add("funnel", min(0.6 + severity * 0.4, 1.0),
            f"{universe:,}종목에서 {survived}종목이 남았습니다.", universe=universe, survived=survived)

    # --- events ------------------------------------------------------------
    today_exits = [item for item in closed if str(item.get("exit_date"))[:10] == today.isoformat()]
    if today_exits:
        worst = min(float(item["realized_return"]) for item in today_exits)
        add("exits", 0.55 + min(abs(worst) * 3, 0.45),
            f"오늘 {len(today_exits)}건을 정리했습니다.", count=len(today_exits), worst=round(worst, 4))

        stopped = [item for item in today_exits if str(item.get("exit_reason")) == "stop_loss"]
        if stopped:
            add("stop_worked", 0.6 + min(abs(worst) * 3, 0.4),
                f"손절선에서 {len(stopped)}건이 정리됐습니다.", count=len(stopped))
        won = [item for item in today_exits if str(item.get("exit_reason")) == "take_profit"]
        if won:
            best = max(float(item["realized_return"]) for item in won)
            add("take_profit", 0.7 + min(best * 3, 0.3), f"목표가에 {len(won)}건이 닿았습니다.", best=round(best, 4))

    if closed:
        deepest = min(closed, key=lambda item: float(item["realized_return"]))
        move = abs(float(deepest["realized_return"]))
        # and the cut needs the sessions to draw, not only the number
        drawable = bool((payload.get("candles") or {}).get("bars"))
        if move >= 0.10 and str(deepest.get("exit_date"))[:10] == today.isoformat() and drawable:
            add("big_mover", min(move * 4, 1.0),
                f"{deepest.get('ticker_name')} 한 종목이 {move * 100:.1f}% 움직였습니다.",
                ticker=deepest.get("ticker_name"))

    if "paper" in books and "rules" in books:
        gap = books["paper"] - books["rules"]
        previous = _last_detail(history, "crossover", "gap")
        if previous is not None and (gap >= 0) != (float(previous) >= 0):
            add("crossover", min(abs(gap) * 25, 1.0), "AI 계좌와 규칙 계좌의 순서가 뒤집혔습니다.", gap=round(gap, 5))

    # --- the argument behind one of today's buys ---------------------------
    # A transcript is only worth a cut when the two sides actually disagreed:
    # both arguing the same way is a formality, not a story.
    debate = payload.get("debate") or {}
    turns = debate.get("turns") or {}
    if turns.get("bull") and turns.get("bear"):
        def _sure(role: str) -> float:
            try:
                return float(((turns.get(role) or {}).get("data") or {}).get("conviction") or 0.0)
            except (TypeError, ValueError):
                return 0.0

        bull, bear = _sure("bull"), _sure("bear")
        decision = debate.get("decision") or {}
        bought = str(decision.get("stage") or "") == "ordered"
        # the loudest version: the surer side lost
        upset = (bear > bull and bought) or (bull > bear and not bought)
        add(
            "debate",
            1.0 if upset else max(0.45, min(abs(bull - bear) * 4, 0.9)),
            (
                "더 확신한 쪽과 반대로 판정이 났습니다."
                if upset
                else f"강세 {bull:.2f} 대 약세 {bear:.2f} 로 붙었습니다."
            ),
            bull=round(bull, 3),
            bear=round(bear, 3),
            ticker=str(decision.get("ticker_name") or decision.get("ticker_code") or ""),
        )

    if closed_count in MILESTONES:
        add("milestone", 1.0, f"{closed_count}번째 거래를 정리했습니다.", count=closed_count)

    # --- the calendar ------------------------------------------------------
    if today.weekday() == 4:
        # Two points is a line segment, not a curve. The cut waits until there
        # is enough of it to be worth watching rather than reading.
        drawn = len((payload.get("curve") or {}).get("points") or [])
        if drawn >= MIN_CURVE_DAYS:
            add("weekly", 0.8, f"한 주가 끝났고, {drawn}거래일치 선이 쌓였습니다.", days=drawn)
    if (today + timedelta(days=1)).day == 1:
        add("monthly", 0.95, "한 달이 끝났습니다.")

    # --- and the shelf, which is what a quiet day is for --------------------
    # An explainer only goes on the shelf once its evidence beat has something
    # in it. explain_debate needs both books, explain_open needs closed trades;
    # a cut that explains the method and then shows an empty table is worse
    # than the quiet day it was meant to fill.
    from .topics import BY_TOPIC

    for key in ("explain_stop", "explain_debate", "explain_open"):
        topic = BY_TOPIC.get(key)
        if topic is not None and not topic.ready(payload):
            continue
        # 0.3 kept these off the air for a month at a time. They are the only
        # cuts that explain the thing rather than report on it, so they are
        # worth roughly a quiet day's account cut.
        add(key, 0.62, "조용한 날을 위한 상비 콘텐츠입니다.")

    found.sort(key=lambda item: (-item.score, item.story.key))
    return found


def _last_detail(ledger: Sequence[Mapping[str, Any]], key: str, field_name: str) -> Any:
    for row in reversed(list(ledger)):
        if str(row.get("story")) == key and field_name in row:
            return row[field_name]
    return None


def plan(payload: Mapping[str, Any], *, now: datetime | None = None, ledger: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Today's decision: what to make, why, and what else was in the running."""

    candidates = evaluate(payload, now=now, ledger=ledger)
    playable = [item for item in candidates if item.story.renderable]
    chosen = playable[0] if playable else None
    return {
        "date": _today(now).isoformat(),
        "chosen": chosen.as_dict() if chosen else None,
        "story": chosen.story.key if chosen else None,
        "renderer": chosen.story.renderer if chosen else None,
        "reason": chosen.reason if chosen else "오늘 발동한 스토리 중 만들 수 있는 것이 없습니다.",
        "candidates": [item.as_dict() for item in candidates],
        "waiting": [story.key for story in STORIES if not story.renderable],
    }


__all__ = [
    "BY_KEY", "Candidate", "LEDGER_ENV", "MILESTONES", "STORIES", "Story",
    "evaluate", "ledger_path", "plan", "read_ledger", "record_published",
]

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
    Story("rejected", "거른 종목의 그 뒤", "event", 1.0, 5, "rejected"),
    Story("debate", "강세 AI vs 약세 AI", "event", 1.0, 2, "debate"),
    Story("milestone", "이정표", "event", 1.0, 30, None),
    # --- the calendar ------------------------------------------------------
    Story("weekly", "주간 성적표", "periodic", 1.0, 6, "curve"),
    Story("monthly", "월간 결산", "periodic", 1.0, 25, None),
    # The one story the project can make on demand: a sweep is work that
    # has to happen before a rule changes anyway, and it needs no market
    # event and no closed trade to be worth showing.
    Story("rule_test", "이번에 시험해본 규칙", "periodic", 1.0, 12, "sweep"),
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
    # The shortlist scored against itself: the only cut that can say the
    # picking did not work. It scores high either way, because a day the
    # book was right is worth the same airtime as a day it was not.
    shortlist = payload.get("rejected") or {}
    if shortlist.get("rows") and shortlist.get("bought_count") and shortlist.get("passed_count"):
        gap = abs(float(shortlist.get("passed_alpha") or 0.0) - float(shortlist.get("bought_alpha") or 0.0))
        add("rejected", min(0.7 + gap * 8, 1.0),
            f"넘긴 {int(shortlist['passed_count'])}종목과 산 {int(shortlist['bought_count'])}종목을 견줬습니다.",
            gap=round(gap, 5))

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

    # A sweep that was replayed recently enough to still describe the rules
    # in force. An old one is a museum piece, not this week's experiment.
    sweep = payload.get("sweep") or {}
    variants = list(sweep.get("variants") or [])
    if len(variants) >= 4 and sweep.get("ran_on"):
        try:
            age = (today - date.fromisoformat(str(sweep["ran_on"])[:10])).days
        except ValueError:
            age = 999
        if age <= 45:
            spread = abs(float(variants[0].get("total_return") or 0.0)
                         - float(variants[-1].get("total_return") or 0.0))
            add("rule_test", min(0.6 + spread * 0.4, 1.0),
                f"규칙 {len(variants)}가지를 같은 구간에 돌려 비교했습니다.",
                variants=len(variants), age=age)

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


# ======================================================================
# WEEK1_MIX_TEST — 2026-11-09 week-1 story-mix test. ONE variable changed:
# which story wins a day that fires more than one candidate. Layout, hook,
# title format and voice are untouched; this only reorders/blocks within
# `plan()`'s existing candidate list.
#
# Why: jobs/2026-11-06-trading-repo-review/CONTENT-DIRECTION.md measured
# record ("AI 모의계좌 성적 전부 공개") at ~690 median views, picks at 1,030,
# debate at ~438, against funnel ("...종목에서 1종목") at 135 despite being a
# third of all uploads, and explain_stop/explain_open/explain_debate/
# rule_test reran under the *same* title and fell every time they did
# (753→48→2, 41→26→25). Baseline before this test, channel-wide: overall
# median 142 views, feed "계속 시청" (stayed watching) 21.9%.
#
# To revert: delete this whole block (constants through `_week1_mix_pick`)
# and the single call to `_week1_mix_pick(...)` inside `plan()` — `plan()`
# goes back to `playable[0]` with no quotas and no rerun check.
# ======================================================================
WEEK1_MIX_TEST_WEEKLY_CAPS: dict[str, int] = {"funnel": 1, "picks": 1, "debate": 1}
WEEK1_MIX_TEST_RECORD_TARGET = 2
WEEK1_MIX_TEST_TITLE_WINDOW_DAYS = 30


def _week1_iso_week(day: date) -> tuple[int, int]:
    year, week, _ = day.isocalendar()
    return year, week


def _week1_counts_this_week(ledger: Sequence[Mapping[str, Any]], today: date) -> dict[str, int]:
    """How many times each story key already ran in today's Mon-Sun week.

    Reads every ledger row regardless of its ``confirmed`` flag, the same way
    `_novelty` already does for cooldown — a failed attempt still occupied
    its slot in the week, so it still counts against the quota.
    """

    target = _week1_iso_week(today)
    counts: dict[str, int] = {}
    for row in ledger:
        try:
            when = date.fromisoformat(str(row.get("date"))[:10])
        except ValueError:
            continue
        if _week1_iso_week(when) != target:
            continue
        key = str(row.get("story"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _week1_recent_titles(ledger: Sequence[Mapping[str, Any]], today: date,
                          *, days: int = WEEK1_MIX_TEST_TITLE_WINDOW_DAYS) -> set[str]:
    """Titles already published in the trailing window, for the rerun block."""

    titles: set[str] = set()
    for row in ledger:
        try:
            when = date.fromisoformat(str(row.get("date"))[:10])
        except ValueError:
            continue
        if when > today or (today - when).days > days:
            continue
        title = str(row.get("title") or "").strip()
        if title:
            titles.add(title)
    return titles


def _week1_prospective_title(candidate: Candidate, payload: Mapping[str, Any], *, now: datetime | None) -> str | None:
    """The title this candidate's video would carry, so a rerun is caught
    before anything is built.

    A story whose title would carry new numbers is a different string and so
    is never blocked by this — only an unchanged title (explain_* and, on a
    repeat variant set, rule_test) is. If the title cannot be produced from
    this payload, this returns None and the candidate is treated as not
    blocked: a day with no story is worse than one rerun slipping through.
    """

    try:
        from .stories import build as _build_story

        board = _build_story(candidate.story.renderer, payload, now=now, story=candidate.story.key)
        return board.title
    except Exception:
        return None


def _week1_mix_pick(
    playable: list[Candidate],
    payload: Mapping[str, Any],
    ledger: Sequence[Mapping[str, Any]],
    today: date,
    *,
    now: datetime | None,
) -> tuple[Candidate | None, dict[str, Any]]:
    """Today's winner under the week-1 mix test, and why.

    Baseline behaviour (what this replaces) is simply `playable[0]` — highest
    score, no quotas, no rerun check — and that is exactly the fallback below
    when every candidate is blocked, so a day never goes out empty.
    """

    if not playable:
        return None, {"applied": False, "reason": "오늘 올릴 수 있는 후보가 없습니다."}

    counts = _week1_counts_this_week(ledger, today)
    recent_titles = _week1_recent_titles(ledger, today)

    eligible: list[Candidate] = []
    blocked: list[tuple[str, str]] = []
    for item in playable:
        key = item.story.key
        cap = WEEK1_MIX_TEST_WEEKLY_CAPS.get(key)
        if cap is not None and counts.get(key, 0) >= cap:
            blocked.append((key, f"주간 한도 {cap}회 소진"))
            continue
        title = _week1_prospective_title(item, payload, now=now)
        if title is not None and title in recent_titles:
            blocked.append((key, f"최근 {WEEK1_MIX_TEST_TITLE_WINDOW_DAYS}일 내 동일 제목 재사용 차단"))
            continue
        eligible.append(item)

    if not eligible:
        fallback = playable[0]
        reasons = "; ".join(f"{key}:{reason}" for key, reason in blocked) or "사유 없음"
        return fallback, {
            "applied": True, "fallback": True, "counts_this_week": counts, "blocked": blocked,
            "reason": f"모든 후보가 주간 믹스 규칙에 막혀 평소 점수순(1위)으로 대체: {reasons}",
        }

    # record is under its weekly target (2/주): nudge it ahead of a same-day
    # tie or near-tie instead of only ever winning when it already has the
    # top raw score. This is additive, not an override — a real event, a
    # periodic report or a sharp funnel cut still wins the day on its own
    # score the way it always has; `RECORD_NUDGE` only closes small gaps.
    RECORD_NUDGE = 0.12
    record_item = next((item for item in eligible if item.story.key == "record"), None)
    record_boosted = record_item is not None and counts.get("record", 0) < WEEK1_MIX_TEST_RECORD_TARGET

    def _effective_score(item: Candidate) -> float:
        return item.score + (RECORD_NUDGE if record_boosted and item.story.key == "record" else 0.0)

    eligible.sort(key=lambda item: (-_effective_score(item), item.story.key))

    # picks/debate outrank funnel whenever both cleared today's bar — the
    # content review found funnel's median (135) far below picks' (1,030) and
    # debate's (~438), and funnel already keeps its own weekly cap above.
    if eligible[0].story.key == "funnel":
        better = next((item for item in eligible if item.story.key in ("picks", "debate")), None)
        if better is not None:
            eligible.remove(better)
            eligible.insert(0, better)

    winner = eligible[0]
    return winner, {
        "applied": True, "fallback": False, "counts_this_week": counts,
        "blocked": blocked, "record_boosted": record_boosted,
    }
# ======================================================= end WEEK1_MIX_TEST


def plan(payload: Mapping[str, Any], *, now: datetime | None = None, ledger: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Today's decision: what to make, why, and what else was in the running."""

    candidates = evaluate(payload, now=now, ledger=ledger)
    today = _today(now)
    history = list(ledger if ledger is not None else read_ledger())
    playable = [item for item in candidates if item.story.renderable]
    chosen, mix = _week1_mix_pick(playable, payload, history, today, now=now)
    return {
        "date": today.isoformat(),
        "chosen": chosen.as_dict() if chosen else None,
        "story": chosen.story.key if chosen else None,
        "renderer": chosen.story.renderer if chosen else None,
        "reason": chosen.reason if chosen else "오늘 발동한 스토리 중 만들 수 있는 것이 없습니다.",
        "candidates": [item.as_dict() for item in candidates],
        "waiting": [story.key for story in STORIES if not story.renderable],
        "mix": mix,
    }


__all__ = [
    "BY_KEY", "Candidate", "LEDGER_ENV", "MILESTONES", "STORIES", "Story",
    "WEEK1_MIX_TEST_RECORD_TARGET", "WEEK1_MIX_TEST_TITLE_WINDOW_DAYS",
    "WEEK1_MIX_TEST_WEEKLY_CAPS",
    "evaluate", "ledger_path", "plan", "read_ledger", "record_published",
]

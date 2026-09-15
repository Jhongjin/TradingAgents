"""Turning the day's record into a cut, with the words that go under it.

A story reads the same payload the site renders and decides what the video
says: which number is the hook, which rows are worth showing, what the closing
line is. Nothing here invents a figure. If the account lost money the hook is
the loss, because that is the only version of this channel worth running.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .design import DEFAULT_THEME, korean_date, money, percent, tone
from .scenes import Bars, Hook, Outro, Rows, Scene, Statement

KST = ZoneInfo("Asia/Seoul")

EXIT_LABELS = {
    "stop_loss": "손절",
    "take_profit": "익절",
    "max_holding_days": "기간 종료",
    "news_risk": "악재 감지",
}
RATING_LABELS = {"overweight": "비중 확대", "underweight": "비중 축소", "neutral": "중립"}


@dataclass(frozen=True)
class Storyboard:
    slug: str
    title: str
    description: str
    tags: tuple[str, ...]
    scenes: tuple[Scene, ...]
    theme: str = DEFAULT_THEME
    # Posted under the video as the channel. Short, because the first two
    # lines are all anyone reads before the fold.
    comment: str = ""

    @property
    def seconds(self) -> float:
        return sum(scene.seconds for scene in self.scenes)


def site_url() -> str:
    raw = (os.getenv("TRADINGAGENTS_SITE_BASE_URL") or "https://agenttrust.kr").strip()
    return raw.rstrip("/")


def _display_host() -> str:
    return site_url().split("://", 1)[-1]


def _telegram_line() -> str:
    handle = telegram_handle()
    if handle:
        return f"아침 알림 텔레그램 → https://t.me/{handle.lstrip('@')}"
    return f"아침 알림 받기 → {site_url()}/start"


def _comment(lead: str, *, path: str, campaign: str, stamp: str) -> str:
    """The comment that goes under the video, as the channel.

    A viewer who got this far wants the receipts, so the first line says what
    is on the other end and the second is the link. The landing page follows
    for whoever arrived with no idea what this channel is.
    """

    lines = [lead, _link(path, campaign, stamp=stamp), "", f"처음이시면 → {_link('/start', campaign, stamp=stamp)}"]
    handle = telegram_handle()
    if handle:
        lines.append(f"매일 아침 먼저 받기 → https://t.me/{handle.lstrip('@')}")
    return "\n".join(lines)


def _link(path: str, campaign: str, *, stamp: str) -> str:
    return f"{site_url()}{path}?utm_source=youtube&utm_medium=shorts&utm_campaign={campaign}&utm_content={stamp}"


def telegram_handle() -> str:
    """The public channel the outro points at, if one has been opened.

    Deliberately not the bot: a viewer cannot subscribe to it without signing
    up first, so pointing a video at the bot would promise something the tap
    does not deliver. Until a channel exists the outro sends people to the
    site, which is where the connection is actually made.
    """

    for name in ("TRADINGAGENTS_TELEGRAM_CHANNEL", "TELEGRAM_CHANNEL_USERNAME"):
        raw = (os.getenv(name) or "").strip()
        if raw:
            return raw if raw.startswith("@") else f"@{raw.rsplit('/', 1)[-1]}"
    return ""


def spoken_percent(value: float | None, *, digits: int = 2) -> str:
    """A figure a narrator can read: the sign as a word, the unit spelled out."""

    if value is None:
        return "알 수 없음"
    magnitude = f"{abs(value) * 100:.{digits}f}".rstrip("0").rstrip(".")
    return f"{'마이너스 ' if value < 0 else '플러스 ' if value > 0 else ''}{magnitude}퍼센트"


def spoken_money(value: float | None) -> str:
    """Rounded to a unit a person would say out loud, not read digit by digit."""

    if not value:
        return "0원"
    amount = abs(float(value))
    sign = "손실 " if value < 0 else "이익 "
    if amount >= 100_000_000:
        return f"{sign}{amount / 100_000_000:.1f}억원"
    if amount >= 10_000:
        return f"{sign}{amount / 10_000:,.0f}만원"
    return f"{sign}{amount:,.0f}원"


def short_date(value: Any) -> str:
    """9/10, because a list row has no room for the long form."""

    parts = str(value or "")[:10].split("-")
    return f"{int(parts[1])}/{int(parts[2])}" if len(parts) == 3 else str(value or "")


def _today(now: datetime | None = None) -> date:
    return (now or datetime.now(KST)).astimezone(KST).date()


def _rating(value: Any) -> str:
    return RATING_LABELS.get(str(value or "").strip().lower(), str(value or "").strip())


def _account_rows(payload: Mapping[str, Any]) -> tuple[dict, ...]:
    rows = []
    for item in payload.get("accounts") or []:
        summary = item.get("summary") or {}
        value = summary.get("total_return")
        if value is None:
            continue
        rows.append(
            {
                "label": str(item.get("label") or item.get("key")),
                "value": float(value),
                "text": percent(float(value)),
                "sub": f"보유 {int(summary.get('open_count') or 0)}종목   정리 {int(summary.get('closed_count') or 0)}건",
            }
        )
    return tuple(rows)


def _outro(*, headline: tuple[str, ...], call: str, narration: str) -> Outro:
    """Every cut ends the same way: where the record lives, then the alerts."""

    handle = telegram_handle()
    return Outro(
        headline=headline,
        call=call,
        url=_display_host(),
        telegram=handle or f"{_display_host()}/start",
        telegram_line=(
            "매일 아침 선별 결과와 청산 알림을 텔레그램으로 먼저"
            if handle
            else "가입하고 텔레그램을 연결하면 매일 아침 먼저 받습니다"
        ),
        seconds=5.4,
        narration=narration,
    )


def build_record(payload: Mapping[str, Any], *, now: datetime | None = None, theme: str = DEFAULT_THEME) -> Storyboard:
    """The whole record so far: what was closed, and what it did to the account.

    This is the cut for a channel nobody knows yet. It has a beginning and an
    end inside thirty seconds, and it opens with the loss, which is the part
    no other channel shows.
    """

    summary = payload.get("summary") or {}
    closed = sorted(
        (item for item in payload.get("closed") or [] if item.get("realized_return") is not None),
        key=lambda item: float(item["realized_return"]),
    )
    total_return = float(summary.get("total_return") or 0.0)
    initial = float(summary.get("initial_cash") or 0.0)
    realized = float(summary.get("realized_pnl") or 0.0)
    closed_count = int(summary.get("closed_count") or len(closed))
    win_count = int(summary.get("win_count") or 0)
    stamp = _today(now).strftime("%Y%m%d")
    worst = closed[0] if closed else None

    verdict = "전부 손실이었습니다." if closed and win_count == 0 else f"{win_count}건이 이익이었습니다."
    stopped = [item for item in closed if str(item.get("exit_reason")) == "stop_loss"]

    rows = tuple(
        {
            "label": str(item.get("ticker_name") or item.get("ticker_code")),
            "sub": f"{short_date(item.get('entry_date'))} 매수   {short_date(item.get('exit_date'))} 정리   {item.get('account_label') or ''}",
            "entry": item.get("entry_price"),
            "exit": item.get("exit_price"),
            "stop": item.get("stop_price"),
            "value": percent(float(item["realized_return"])),
            "colour": tone(float(item["realized_return"])),
            "badge": EXIT_LABELS.get(str(item.get("exit_reason")), "정리"),
            "badge_colour": "warn",
        }
        for item in closed[:5]
    )

    scenes: list[Scene] = [
        Hook(
            eyebrow=f"AI 모의 계좌 {korean_date(_today(now).isoformat())} 기준",
            value_to=total_return,
            value_colour=tone(total_return),
            caption=f"{initial / 100_000_000:.1f}억원으로 시작한 계좌의 지금 성적",
            lines=(f"지금까지 정리한 {closed_count}건,", verdict),
            seconds=3.4,
            narration=f"AI한테 종목을 고르게 하고, 모의 계좌로 진짜 담아봤습니다. 지금 성적, {spoken_percent(total_return)}.",
        ),
        Rows(
            eyebrow="정리한 거래 전부",
            heading="하나도 빼지 않았습니다",
            rows=rows,
            note=f"실현 손익 {money(realized)}",
            seconds=3.0 + len(rows) * 0.9,
            narration=(
                f"정리한 {closed_count}건입니다. 좋은 것만 골라 보여드리는 게 아니라, 전부요."
                + (f" 제일 크게 물린 건 {spoken_percent(float(worst['realized_return']), digits=1)}. 하루 만에 그렇게 됐어요." if worst else "")
            ),
        ),
    ]

    if worst is not None:
        scenes.append(
            Statement(
                eyebrow="그런데",
                lines=(f"한 종목은 {percent(float(worst['realized_return']), digits=1)}였는데", "계좌 전체는"),
                highlight=percent(total_return),
                highlight_colour=tone(total_return),
                stamp="손절" if stopped else "정리",
                inverted=True,
                caption=f"{len(stopped)}건 모두 손절선에서 정리됐습니다.\n종목은 틀렸지만 손실은 정해둔 선에서 멈췄습니다.",
                seconds=4.6,
                narration=(
                    f"그런데 계좌 전체는 {spoken_percent(total_return)}에서 멈췄죠. "
                    "살 때 나갈 가격을 미리 정해뒀거든요. 종목은 틀렸는데, 손실은 안 틀린 겁니다."
                ),
            )
        )

    accounts = _account_rows(payload)
    if accounts:
        scenes.append(
            Bars(
                eyebrow="세 계좌를 나란히",
                heading="AI가 보탠 몫을 봅니다",
                items=accounts,
                note="같은 날 같은 후보로, 확인 방식만 다르게 굴립니다.",
                seconds=5.8,
                narration="같은 후보를 놓고 계좌를 따로 굴립니다. AI가 한 번 더 들여다본 쪽, 규칙만 보는 쪽. 그 차이가 곧 AI 몫이죠.",
            )
        )

    scenes.append(_outro(
        headline=("맞힌 날만 올리는 채널은", "이미 많습니다."),
        call="틀린 날까지 전부 남는 기록",
        narration=(
            "맞힌 날만 올리는 채널, 이미 많잖아요. 여긴 틀린 날도 그대로 남습니다. "
            "내일 아침 뭘 골랐는지는 텔레그램으로 먼저 갑니다."
        ),
    ))

    return Storyboard(
        slug=f"record-{stamp}",
        title=f"AI 모의계좌 성적 전부 공개 | 정리한 {closed_count}건과 {percent(total_return)}",
        description=(
            f"AI가 고른 종목을 모의 계좌가 담고, 정리한 결과를 하나도 빼지 않고 공개합니다.\n\n"
            f"전체 기록 → {_link('/paper', 'record', stamp=stamp)}\n"
            f"검증 결과 → {_link('/outcomes', 'record', stamp=stamp)}\n"
            f"{_telegram_line()}\n\n"
            "AI 실험 기록이며 매매 권유가 아닙니다. 모의 계좌 기록이고 실계좌 주문은 없습니다.\n"
            "#주식 #AI주식 #모의투자 #코스피 #손절"
        ),
        tags=("주식", "AI주식", "모의투자", "코스피", "손절", "투자기록"),
        scenes=tuple(scenes),
        theme=theme,
        comment=_comment(
            f"영상에 나온 {closed_count}건, 고른 이유부터 정리한 값까지 전부 여기 있습니다.",
            path="/paper", campaign="record", stamp=stamp,
        ),
    )


def build_picks(payload: Mapping[str, Any], *, now: datetime | None = None, theme: str = DEFAULT_THEME) -> Storyboard:
    """What the AI book is holding right now, with the levels it set on entry."""

    positions = [item for item in payload.get("positions") or [] if str(item.get("account")) == "paper"]
    positions.sort(key=lambda item: str(item.get("entry_date") or ""), reverse=True)
    stamp = _today(now).strftime("%Y%m%d")
    names = "·".join(str(item.get("ticker_name") or "") for item in positions[:3]) or "보유 종목"

    rows = tuple(
        {
            "label": str(item.get("ticker_name") or item.get("ticker_code")),
            "sub": f"{short_date(item.get('entry_date'))} 매수   평단 {float(item.get('average_price') or 0):,.0f}원",
            "value": f"{float(item.get('target_price') or 0):,.0f}원",
            "colour": "up",
            "badge": _rating(item.get("decision_rating")) or "판정 없음",
            "badge_colour": "accent",
        }
        for item in positions[:5]
    )
    stops = tuple(
        {
            "label": str(item.get("ticker_name") or item.get("ticker_code")),
            "value": f"{float(item.get('stop_price') or 0):,.0f}원",
            "colour": "down",
            "sub": f"평단 대비 {percent((float(item.get('stop_price') or 0) / float(item.get('average_price') or 1)) - 1, digits=1)}",
        }
        for item in positions[:5]
    )

    scenes: tuple[Scene, ...] = (
        Hook(
            eyebrow=f"AI 확인 계좌 {korean_date(_today(now).isoformat())}",
            value=str(len(positions)) + "종목",
            value_colour="ink",
            caption="지금 담고 있는 종목입니다",
            lines=("사기 전에 목표가와", "손절가를 먼저 정했습니다."),
            seconds=3.4,
            narration=f"AI 계좌가 지금 들고 있는 종목, {len(positions)}개예요. 사기 전에 나갈 가격부터 정해뒀습니다.",
        ),
        Rows(
            eyebrow="보유 종목과 목표가",
            heading=names if len(names) <= 22 else "지금 담고 있는 종목",
            rows=rows,
            note="목표가는 AI 토론이 정한 값이며 도달을 보장하지 않습니다.",
            seconds=3.0 + len(rows) * 0.9,
            narration="종목이랑 목표가입니다. 닿는다는 보장은 없어요. 어디까지 보고 샀는지를 적어두는 거죠.",
        ),
        Rows(
            eyebrow="그리고 손절가",
            heading="틀렸을 때 나갈 선",
            rows=stops,
            note="이 선에 닿으면 다음 실행에서 자동으로 정리됩니다.",
            seconds=2.6 + len(stops) * 0.7,
            narration="그리고 이건 틀렸을 때 나갈 선. 여기 닿으면 다음 실행에서 알아서 정리합니다.",
        ),
        _outro(
            headline=("결과는 며칠 뒤", "이 채널에 그대로 올라옵니다."),
            call="근거와 토론 전문",
            narration=(
                "맞았는지 틀렸는지는 며칠 뒤 이 채널에 그대로 올라옵니다. "
                "정리되는 순간은 텔레그램으로 먼저 갑니다."
            ),
        ),
    )

    return Storyboard(
        slug=f"picks-{stamp}",
        title=f"AI가 지금 담고 있는 {len(positions)}종목 | 목표가·손절가 공개",
        description=(
            "AI가 고른 종목과, 매수와 동시에 정한 목표가·손절가입니다. 결과는 며칠 뒤 같은 채널에 올라옵니다.\n\n"
            f"오늘의 선별 → {_link('/harness', 'picks', stamp=stamp)}\n"
            f"모의 계좌 → {_link('/paper', 'picks', stamp=stamp)}\n"
            f"{_telegram_line()}\n\n"
            "AI 실험 기록이며 매매 권유가 아닙니다. 모의 계좌 기록이고 실계좌 주문은 없습니다.\n"
            "#주식 #AI주식 #모의투자 #코스피 #목표가"
        ),
        tags=("주식", "AI주식", "모의투자", "코스피", "목표가", "손절가"),
        scenes=scenes,
        theme=theme,
        comment=_comment(
            "이 종목들이 며칠 뒤 어떻게 정리됐는지는 같은 자리에 그대로 남습니다.",
            path="/harness", campaign="picks", stamp=stamp,
        ),
    )


STORIES: dict[str, Callable[..., Storyboard]] = {
    "record": build_record,
    "picks": build_picks,
}


def build(name: str, payload: Mapping[str, Any], *, now: datetime | None = None, theme: str = DEFAULT_THEME) -> Storyboard:
    if name not in STORIES:
        raise ValueError(f"알 수 없는 스토리 {name!r}. 가능한 값: {', '.join(sorted(STORIES))}")
    return STORIES[name](payload, now=now, theme=theme)


__all__ = ["STORIES", "Storyboard", "build", "build_picks", "build_record", "short_date", "site_url"]

"""Whether today's short actually reached the channel, asked from outside this PC.

Every way the daily short has been lost so far left this machine unable to say
so. A restart at 08:43 took the process with it; a run stuck for an hour was
killed by the scheduler with its output still in Python's buffer; n8n answered
a refused upload with an empty 200; and Telegram stopped answering this network
on 09-21, so even a run that knew it had failed could not have said it.

So the check does not ask the machine. It asks the channel's public feed, from
a runner somewhere else, after the last attempt of the day should have
finished. A day with nothing on the feed is a failure whatever the reason was.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Callable, Sequence

CHANNEL_ID = "UCJmQOI0Tx5SFzQS30BqHrkw"
FEED_URL = "https://www.youtube.com/feeds/videos.xml"
KST = timezone(timedelta(hours=9))

_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


@dataclass(frozen=True)
class FeedEntry:
    video_id: str
    title: str
    published: datetime

    @property
    def day(self) -> date:
        return self.published.astimezone(KST).date()


def parse_feed(xml_text: str) -> list[FeedEntry]:
    root = ET.fromstring(xml_text)
    entries: list[FeedEntry] = []
    for node in root.findall("atom:entry", _NS):
        video_id = (node.findtext("yt:videoId", default="", namespaces=_NS) or "").strip()
        published = (node.findtext("atom:published", default="", namespaces=_NS) or "").strip()
        if not video_id or not published:
            continue
        entries.append(FeedEntry(
            video_id=video_id,
            title=(node.findtext("atom:title", default="", namespaces=_NS) or "").strip(),
            published=datetime.fromisoformat(re.sub(r"Z$", "+00:00", published)),
        ))
    return entries


def fetch_feed(channel_id: str = CHANNEL_ID, *, get: Callable[..., object] | None = None) -> list[FeedEntry]:
    if get is None:
        import requests

        get = requests.get
    response = get(FEED_URL, params={"channel_id": channel_id}, timeout=30)
    response.raise_for_status()                      # type: ignore[attr-defined]
    return parse_feed(response.text)                 # type: ignore[attr-defined]


def published_on(entries: Sequence[FeedEntry], day: date) -> list[FeedEntry]:
    return [entry for entry in entries if entry.day == day]


def last_published(entries: Sequence[FeedEntry]) -> FeedEntry | None:
    return max(entries, key=lambda entry: entry.published, default=None)


def missing_message(day: date, entries: Sequence[FeedEntry]) -> str:
    """The Telegram text for a day with nothing on the channel (HTML parse mode)."""

    last = last_published([entry for entry in entries if entry.day < day])
    since = ""
    if last is not None:
        gap = (day - last.day).days
        since = f"\n마지막 발행: {last.day.isoformat()} ({gap}일 전) · {escape(last.title)}"
    return (
        f"🔴 <b>오늘 쇼츠가 채널에 없습니다</b> · {day.isoformat()}\n"
        f"08:40 · 11:15 · 14:30 세 번 모두 결과가 없습니다.{since}\n\n"
        f"PC 로그: logs\\daily-short-{day.isoformat()}.log\n"
        "다시 올리기: automation\\daily-short.cmd"
    )


__all__ = ["CHANNEL_ID", "FeedEntry", "fetch_feed", "last_published", "missing_message", "parse_feed", "published_on"]

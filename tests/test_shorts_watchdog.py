from datetime import date

from tradingagents.shorts.watchdog import last_published, missing_message, parse_feed, published_on

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <yt:videoId>QMh-qLW6Cj4</yt:videoId>
  <title>AI 모의계좌 16거래일 | 계좌 -3.55% vs KOSPI -0.89%</title>
  <published>2026-10-02T02:18:47+00:00</published>
 </entry>
 <entry>
  <yt:videoId>P_UlzFwsFPk</yt:videoId>
  <title>343종목에서 1종목 | AI가 거른 과정 전부 공개</title>
  <published>2026-09-24T23:46:57+00:00</published>
 </entry>
</feed>"""


def test_a_morning_upload_counts_for_the_korean_day_not_the_utc_one():
    entries = parse_feed(FEED)
    # 23:46 UTC on 09-24 is 08:46 on 09-25 in Seoul
    assert [e.video_id for e in published_on(entries, date(2026, 9, 25))] == ["P_UlzFwsFPk"]
    assert published_on(entries, date(2026, 9, 24)) == []
    assert [e.video_id for e in published_on(entries, date(2026, 10, 2))] == ["QMh-qLW6Cj4"]


def test_a_missing_day_says_how_long_the_channel_has_been_quiet():
    entries = parse_feed(FEED)
    assert last_published(entries).video_id == "QMh-qLW6Cj4"
    text = missing_message(date(2026, 10, 5), entries)
    assert "2026-10-05" in text and "3일 전" in text and "daily-short-2026-10-05.log" in text
    assert "&lt;" not in text and "| 계좌" in text


def test_an_empty_feed_still_produces_an_alert():
    assert "오늘 쇼츠가 채널에 없습니다" in missing_message(date(2026, 10, 5), [])


def test_checking_a_past_day_counts_back_from_that_day():
    text = missing_message(date(2026, 10, 1), parse_feed(FEED))
    assert "2026-09-25 (6일 전)" in text

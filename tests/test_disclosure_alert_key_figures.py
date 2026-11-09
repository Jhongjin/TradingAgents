"""Key figures under a disclosure-alert title, for the filing types where the
title alone hides the number a member actually needs (same report-type gate as
``tradingagents.dataflows.dart._is_body_worthy``).

Bodies here are already-flattened "label | value" text, the exact output
shape of ``dart.get_disclosure_body`` (see tests/test_dart_disclosure_body.py
for the XML/HTML -> "label | value" step) — these tests are only about what
``disclosure_alerts`` does with that text, so no DART fixtures or network are
needed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from tradingagents.site.disclosure_alerts import (
    _earnings_figures,
    _extract_key_figures,
    notify_disclosure_alerts,
)
from tradingagents.site.notifications import TelegramClient, TelegramConfig
from tradingagents.storage import (
    ManualTradeInput,
    NotificationChannelInput,
    StorageRepository,
    create_storage_engine,
)

USER = "22222222-2222-4222-8222-222222222222"

CB_BODY = "\n".join(
    [
        "2. 사채의 권면(전자등록)총액 (원) | 30,000,000,000",
        "전환비율 (%) | 100",
        "전환가액 (원/주) | 4,290",
        "전환가액 결정방법 | " + "아주 긴 산정 방식 설명 문단" * 5,  # > 40 chars, must be skipped
    ]
)

RIGHTS_BODY = "\n".join(
    [
        "1. 신주의 종류와 수 | 보통주식 (주) | 1,500,000",
        "2. 1주당 액면가액 (원) | 100",
        "6. 신주 발행가액 | 보통주식 (원) | 13,000",
        "운영자금 (원) | 599,989,000",
    ]
)

BUYBACK_BODY = "\n".join(
    [
        "1. 취득예정주식(주) | 보통주식 | 200,462",
        "2. 취득예정금액(원) | 보통주식 | 5,693,131,798",
    ]
)

EARNINGS_BODY = "\n".join(
    [
        "매출액 | 당해실적 | 129,250 | 162,844 | -20.6 | - | 96,315 | 34.2 | -",
        "영업이익 | 당해실적 | 4,039 | 9,595 | -57.9 | - | 13,364 | -69.8 | -",
    ]
)

NO_MATCH_CB_BODY = "\n".join(
    [
        "1. 사채의 종류 | 회차 | 2 | 종류 | 무기명식 무이권부 무보증 사모 전환사채",
        "5. 사채만기일 | 2031년 11월 16일",
    ]
)


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


class FakeTelegram(TelegramClient):
    def __init__(self):
        super().__init__(TelegramConfig(bot_token="t", bot_username=None, webhook_secret="s"), transport=lambda *a, **k: {"ok": True})
        self.messages = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))
        return {"ok": True}


def _seed(repo: StorageRepository) -> None:
    watchlist = repo.create_watchlist(user_id=USER, name="관심")
    repo.add_watchlist_item(watchlist_id=watchlist, ticker_code="005930", ticker_name="삼성전자")
    repo.upsert_notification_channel(
        NotificationChannelInput(user_id=USER, channel="telegram", external_id="999", enabled=True, linked_at=datetime.now(timezone.utc))
    )


def _send(repo, client, report_name, body_fetcher):
    rows = {"005930": [{"receipt_no": "20261109000001", "report_name": report_name, "filed_at": "20261109"}]}
    return notify_disclosure_alerts(
        repo,
        client,
        site_base_url="https://agenttrust.kr",
        fetcher=lambda code, days: rows.get(code, []),
        body_fetcher=body_fetcher,
    )


# -- unit-level: pure function, no repo/telegram involved -------------------


def test_cb_figures_pick_face_amount_and_conversion_price_only():
    figures = _extract_key_figures("전환사채권발행결정", CB_BODY)
    assert figures == ["권면총액 30,000,000,000", "전환가액 4,290"]


def test_long_prose_row_is_skipped_even_if_label_matches():
    # "전환가액 결정방법" also contains the "전환가액" keyword, but its value is a
    # multi-sentence paragraph, not a figure — the real numeric row must win.
    figures = _extract_key_figures("전환사채권발행결정", CB_BODY)
    assert not any("긴 산정 방식" in f for f in figures)


def test_rights_issue_figures_pick_share_count_price_and_use_of_funds():
    figures = _extract_key_figures("유상증자결정", RIGHTS_BODY)
    assert figures == ["발행주식수 1,500,000", "발행가액 13,000", "조달금액 599,989,000"]


def test_buyback_figures_pick_planned_shares_and_amount():
    figures = _extract_key_figures("자기주식취득결정", BUYBACK_BODY)
    assert figures == ["취득예정주식 200,462", "취득예정금액 5,693,131,798"]


def test_earnings_figures_are_current_quarter_vs_year_ago():
    figures = _earnings_figures(EARNINGS_BODY)
    assert figures == ["매출액 129,250(전년동기 96,315)", "영업이익 4,039(전년동기 13,364)"]


def test_no_matching_label_adds_nothing():
    assert _extract_key_figures("전환사채권발행결정", NO_MATCH_CB_BODY) == []


def test_non_body_worthy_report_name_adds_nothing():
    assert _extract_key_figures("기타공시", CB_BODY) == []


def test_at_most_three_figures_even_when_more_rules_match():
    figures = _extract_key_figures("유상증자결정", RIGHTS_BODY)
    assert len(figures) <= 3


# -- integration-level: through notify_disclosure_alerts --------------------


def test_alert_line_carries_key_figures_for_a_body_worthy_filing():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()

    result = _send(repo, client, "전환사채권발행결정", lambda receipt_no: CB_BODY)

    assert result["status"] == "sent"
    text = client.messages[0][1]
    assert "권면총액 30,000,000,000" in text
    assert "전환가액 4,290" in text


def test_alert_line_unchanged_when_body_fetch_raises():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()

    def _explode(receipt_no):
        raise RuntimeError("DART document.xml unavailable")

    result = _send(repo, client, "전환사채권발행결정", _explode)

    assert result["status"] == "sent"
    text = client.messages[0][1]
    assert "전환사채권발행결정" in text
    assert "권면총액" not in text  # fails closed: no figures, but no exception either


def test_alert_line_unchanged_when_nothing_in_body_matches():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()

    result = _send(repo, client, "전환사채권발행결정", lambda receipt_no: NO_MATCH_CB_BODY)

    assert result["status"] == "sent"
    text = client.messages[0][1]
    assert "전환사채권발행결정" in text
    # No figure line was inserted: title is immediately followed by the filed-at/url line.
    assert "전환사채권발행결정\n " in text


def test_body_fetch_happens_at_most_once_for_an_alerted_filing():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()
    calls = []

    def _counting_fetcher(receipt_no):
        calls.append(receipt_no)
        return CB_BODY

    result = _send(repo, client, "전환사채권발행결정", _counting_fetcher)

    assert result["status"] == "sent"
    assert calls == ["20261109000001"]


def test_body_fetch_is_skipped_entirely_for_non_body_worthy_filings():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()
    calls = []

    def _counting_fetcher(receipt_no):
        calls.append(receipt_no)
        return CB_BODY

    # 단일판매ㆍ공급계약체결 is notable (NOTABLE keyword "공급계약") but not
    # body-worthy — the title alone is the whole story.
    result = _send(repo, client, "단일판매ㆍ공급계약체결", _counting_fetcher)

    assert result["status"] == "sent"
    assert calls == []

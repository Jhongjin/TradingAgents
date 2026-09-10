"""Disclosure alerts: new DART filings on the names a member follows."""

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.disclosure_alerts import ALERT_KEY, is_notable, member_tickers, notify_disclosure_alerts
from tradingagents.site.notifications import TelegramClient, TelegramConfig
from tradingagents.storage import (
    ManualTradeInput,
    NotificationChannelInput,
    StorageRepository,
    create_storage_engine,
)

USER = "11111111-1111-4111-8111-111111111111"


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
    portfolio = repo.create_manual_portfolio(user_id=USER, name="장기")
    repo.add_manual_trade(
        ManualTradeInput(portfolio_id=portfolio, ticker_code="096770", ticker_name="SK이노베이션", side="buy", trade_date=date(2026, 9, 7), price=Decimal("153500"), quantity=10)
    )
    watchlist = repo.create_watchlist(user_id=USER, name="관심")
    repo.add_watchlist_item(watchlist_id=watchlist, ticker_code="005930", ticker_name="삼성전자")
    repo.upsert_notification_channel(
        NotificationChannelInput(user_id=USER, channel="telegram", external_id="777", enabled=True, linked_at=datetime.now(timezone.utc))
    )


FILINGS = {
    "096770": [
        {"receipt_no": "20260910000111", "report_name": "유상증자결정", "filed_at": "20260910"},
        {"receipt_no": "20260910000112", "report_name": "기업설명회(IR)개최", "filed_at": "20260910"},
    ],
    "005930": [{"receipt_no": "20260910000222", "report_name": "단일판매ㆍ공급계약체결", "filed_at": "20260910"}],
}


def test_only_filings_that_move_a_price_are_sent():
    assert is_notable("유상증자결정") and is_notable("감사보고서제출")
    assert is_notable("최대주주변경") and is_notable("매출액또는손익구조30%(대규모법인은15%)이상변동")
    assert not is_notable("기업설명회(IR)개최") and not is_notable("임원ㆍ주요주주특정증권등소유상황보고서")


def test_a_member_is_followed_through_their_journal_and_watchlist():
    repo = _repo()
    _seed(repo)
    names = member_tickers(repo, USER)
    assert names == {"096770": "SK이노베이션", "005930": "삼성전자"}


def test_each_filing_is_announced_once():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()
    fetcher = lambda code, days: FILINGS.get(code, [])

    first = notify_disclosure_alerts(repo, client, site_base_url="https://agenttrust.kr", fetcher=fetcher)
    assert first["status"] == "sent" and first["filings"] == 2  # the IR notice is not one
    text = client.messages[0][1]
    assert "유상증자결정" in text and "공급계약" in text
    assert "기업설명회" not in text
    assert "dart.fss.or.kr" in text and "매매 권유가 아닙니다" in text

    again = notify_disclosure_alerts(repo, client, site_base_url="https://agenttrust.kr", fetcher=fetcher)
    assert again["status"] == "nothing_to_send" and len(client.messages) == 1

    channel = repo.get_notification_channel(USER, "telegram")
    assert set((channel["metadata_json"] or {})[ALERT_KEY]) == {"20260910000111", "20260910000222"}

    later = dict(FILINGS)
    later["005930"] = [*FILINGS["005930"], {"receipt_no": "20260911000333", "report_name": "감사보고서제출", "filed_at": "20260911"}]
    third = notify_disclosure_alerts(repo, client, site_base_url="https://agenttrust.kr", fetcher=lambda code, days: later.get(code, []))
    assert third["filings"] == 1 and "감사보고서" in client.messages[-1][1]


def test_a_broken_dart_feed_sends_nothing_and_raises_nothing():
    repo = _repo()
    _seed(repo)
    client = FakeTelegram()

    def _explode(code, days):
        raise RuntimeError("DART unavailable")

    result = notify_disclosure_alerts(repo, client, fetcher=_explode)
    assert result["status"] == "nothing_to_send" and client.messages == []


def test_the_cron_route_needs_the_worker_token(monkeypatch):
    repo = _repo()
    _seed(repo)
    monkeypatch.setenv("OPERATOR_ACCESS_CODE", "op-token")
    app = create_app(repo=repo, load_repo_from_env=False)
    app.state.telegram_client = FakeTelegram()
    client = TestClient(app)
    assert client.get("/api/cron/notify-disclosures").status_code == 401
    body = client.get("/api/cron/notify-disclosures", headers={"X-TradingAgents-Worker-Token": "op-token"}).json()
    assert body["status"] in {"nothing_to_send", "sent", "not_configured"}

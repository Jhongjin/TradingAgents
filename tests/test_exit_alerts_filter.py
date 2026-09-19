"""An exit alert must describe a sale that happened.

A dry run writes the same decision rows as a real one — that is the point of a
rehearsal — so the announcer has to filter on the run. It did not, and a
--dry-run pass produced "익절 · 모의 303주" for a sale nobody made.
"""

from datetime import datetime, timezone

from tradingagents.site import notifications


class _Repo:
    def __init__(self, rows):
        self.rows = rows
        self.asked = {}
        self.marked = []

    def list_harness_decisions(self, **kwargs):
        self.asked = kwargs
        if kwargs.get("executed_only"):
            return [row for row in self.rows if row.get("_executed")]
        return list(self.rows)

    def list_notification_recipients(self, channel):
        return [{"user_id": "u1", "external_id": "chat-1"}]

    def update_harness_decision_detail(self, decision_id, detail):
        self.marked.append((decision_id, detail))


class _Client:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)
        return {"ok": True}


def _row(code, name, qty, *, executed, notified=None):
    return {"id": f"d-{code}-{qty}", "ticker_code": code, "ticker_name": name,
            "quantity": qty, "as_of_date": "2026-09-18", "reasons_json": ["stop_loss"],
            "detail_json": {"notified_at": notified} if notified else {},
            "_executed": executed}


def _access(monkeypatch):
    monkeypatch.setattr(notifications, "resolve_plan_access",
                        lambda repo, uid, now=None: type("A", (), {"full_access": True})())


def test_a_rehearsal_is_not_announced_as_a_sale(monkeypatch):
    _access(monkeypatch)
    repo = _Repo([_row("010170", "대한광통신", 303, executed=False),
                  _row("041510", "에스엠", 55, executed=True)])
    client = _Client()

    notifications.notify_exit_alerts(repo, client)

    assert repo.asked.get("executed_only") is True
    assert len(client.sent) == 1
    assert "에스엠" in client.sent[0]
    assert "303" not in client.sent[0]


def test_nothing_executed_sends_nothing(monkeypatch):
    _access(monkeypatch)
    repo = _Repo([_row("010170", "대한광통신", 303, executed=False)])
    client = _Client()

    result = notifications.notify_exit_alerts(repo, client)

    assert result["status"] == "nothing_to_send"
    assert client.sent == []


def test_an_announced_exit_is_marked_so_it_does_not_repeat(monkeypatch):
    _access(monkeypatch)
    repo = _Repo([_row("041510", "에스엠", 55, executed=True)])

    notifications.notify_exit_alerts(repo, _Client(), now=datetime(2026, 9, 21, tzinfo=timezone.utc))

    assert len(repo.marked) == 1
    assert repo.marked[0][1]["notified_at"].startswith("2026-09-21")


def test_a_preview_does_not_consume_the_queue(monkeypatch):
    """mark=False: previewing must not spend a notification nobody received."""

    _access(monkeypatch)
    repo = _Repo([_row("041510", "에스엠", 55, executed=True)])

    notifications.notify_exit_alerts(repo, _Client(), mark=False)

    assert repo.marked == []


def test_an_already_announced_exit_is_left_alone(monkeypatch):
    _access(monkeypatch)
    repo = _Repo([_row("041510", "에스엠", 55, executed=True, notified="2026-09-18T10:35:00+00:00")])
    client = _Client()

    result = notifications.notify_exit_alerts(repo, client)

    assert result["status"] == "nothing_to_send"
    assert client.sent == []

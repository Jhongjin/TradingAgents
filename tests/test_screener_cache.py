"""The screener is worked out on a schedule, not while a visitor waits."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradingagents.site import screener_cache
from tradingagents.site.api_app import create_app
from tradingagents.storage import StorageRepository, create_storage_engine
from tradingagents.storage.repository import TEST_DATABASE_URL


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine(TEST_DATABASE_URL))
    repo.create_schema()
    return repo


def _payload(*, marker: str = "cron", count: int = 2) -> dict:
    return {
        "status": "available",
        "mode": "screener",
        "as_of_date": "2026-09-15",
        "marker": marker,
        "candidates": [{"ticker_code": f"00593{index}"} for index in range(count)],
    }


def test_the_cache_keeps_only_the_newest_answer():
    repo = _repo()
    repo.save_cached_payload("screener", _payload(marker="old"))
    repo.save_cached_payload("screener", _payload(marker="new"))

    row = repo.latest_cached_payload("screener")
    assert row["payload_json"]["marker"] == "new"

    # a cache is not a history: the superseded row is gone, not just outranked
    with repo.engine.begin() as conn:
        remaining = conn.exec_driver_sql("select count(*) from cached_payloads").scalar()
    assert remaining == 1

    assert repo.latest_cached_payload("nothing-parked-here") is None


def test_a_parked_answer_goes_stale_but_is_still_offered():
    repo = _repo()
    repo.save_cached_payload("screener", _payload())
    now = datetime.now(timezone.utc)

    payload, fresh = screener_cache.read(repo, now=now)
    assert fresh and payload["marker"] == "cron"

    # yesterday's ranking with a date on it beats a thirty-second wait
    payload, fresh = screener_cache.read(repo, now=now + screener_cache.MAX_AGE + timedelta(minutes=1))
    assert payload is not None and fresh is False

    assert screener_cache.read(None) == (None, False)


def test_a_broken_cache_is_a_miss_not_a_crash():
    class Sulking:
        def latest_cached_payload(self, key):
            raise RuntimeError("no")

        def save_cached_payload(self, *args, **kwargs):
            raise RuntimeError("no")

    assert screener_cache.read(Sulking()) == (None, False)
    assert screener_cache.write(Sulking(), _payload()) is False


def test_the_cron_computes_once_and_parks_it():
    repo = _repo()
    calls = []

    def build(**kwargs):
        calls.append(kwargs)
        return _payload(marker="fresh", count=3)

    report = screener_cache.refresh(repo, builder=build)

    assert len(calls) == 1
    assert report == {"status": "available", "candidates": 3, "as_of_date": "2026-09-15",
                      "stored": True, "seconds": report["seconds"]}
    assert repo.latest_cached_payload("screener")["payload_json"]["marker"] == "fresh"


def test_the_default_request_reads_the_parked_copy_and_never_ranks_the_tape(monkeypatch):
    repo = _repo()
    repo.save_cached_payload("screener", _payload(marker="parked"))

    def explode(**kwargs):
        raise AssertionError("the tape must not be ranked while a visitor waits")

    monkeypatch.setattr("tradingagents.site.api_app.build_screener_payload", explode)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    assert client.get("/api/screener").json()["marker"] == "parked"


def test_asking_for_something_else_is_computed_and_not_parked(monkeypatch):
    repo = _repo()
    repo.save_cached_payload("screener", _payload(marker="parked"))
    monkeypatch.setattr(
        "tradingagents.site.api_app.build_screener_payload",
        lambda **kwargs: _payload(marker=f"live:{kwargs['top_n']}"),
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    assert client.get("/api/screener", params={"top_n": 5}).json()["marker"] == "live:5"
    # and the odd request has not overwritten what everyone else reads
    assert repo.latest_cached_payload("screener")["payload_json"]["marker"] == "parked"


def test_the_first_visitor_computes_it_when_nothing_is_parked_yet(monkeypatch):
    repo = _repo()
    monkeypatch.setattr(
        "tradingagents.site.api_app.build_screener_payload",
        lambda **kwargs: _payload(marker="first"),
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    assert client.get("/api/screener").json()["marker"] == "first"
    # and pays it forward, so the next visitor does not
    assert repo.latest_cached_payload("screener")["payload_json"]["marker"] == "first"


def test_a_stale_copy_is_served_when_the_vendors_are_down(monkeypatch):
    from tradingagents.dataflows.errors import VendorUnavailableError

    repo = _repo()
    repo.save_cached_payload("screener", _payload(marker="yesterday"))
    monkeypatch.setattr(screener_cache, "MAX_AGE", timedelta(seconds=0))

    def down(**kwargs):
        raise VendorUnavailableError("pykrx is not answering")

    monkeypatch.setattr("tradingagents.site.api_app.build_screener_payload", down)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    body = client.get("/api/screener").json()
    assert body["marker"] == "yesterday" and body["stale"] is True


def test_the_cron_route_will_not_run_for_a_stranger(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WORKER_TOKEN", "worker-token")
    repo = _repo()
    monkeypatch.setattr(
        "tradingagents.site.screener_cache.refresh",
        lambda repo, **kwargs: {"status": "available", "candidates": 1, "stored": True},
    )
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    assert client.get("/api/cron/refresh-screener").status_code in (401, 403)
    assert client.get("/api/cron/refresh-screener", headers={"X-TradingAgents-Worker-Token": "nope"}).status_code in (401, 403)

    allowed = client.get("/api/cron/refresh-screener", headers={"X-TradingAgents-Worker-Token": "worker-token"})
    assert allowed.status_code == 200 and allowed.json()["stored"] is True


def test_the_schedule_actually_asks_for_it():
    import json
    from pathlib import Path

    crons = json.loads(Path("vercel.json").read_text(encoding="utf-8"))["crons"]
    slots = [row["schedule"] for row in crons if row["path"] == "/api/cron/refresh-screener"]
    assert len(slots) >= 3                       # open, middle and close of the KRX session
    assert all(slot.endswith("* * 1-5") for slot in slots)

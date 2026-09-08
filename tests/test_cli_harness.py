import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.screener import MarketSnapshot, MarketSnapshotRow, screen_korean_market

runner = CliRunner()


def _points(count=200, drift=0.004):
    rows = []
    close = 50_000.0
    for index in range(count):
        close *= 1 + drift
        rows.append({"date": f"2026-01-{index % 28 + 1:02d}", "close": round(close, 2), "volume": 1_000_000})
    return rows


def _fake_screen(as_of_date, *, config, **kwargs):
    snapshot = MarketSnapshot(
        as_of_date="2026-09-05",
        markets=config.markets,
        rows=[MarketSnapshotRow("005930", "삼성전자", "KOSPI", 70_000.0, 1e7, 5e11, 4e14, 0.5, 12.0, 1.2, 2.0)],
    )
    return screen_korean_market(snapshot=snapshot, history_fetcher=lambda code, s, e: _points(), config=config)


def test_cli_exposes_harness_commands():
    for command in ("screen", "forecast", "playbook", "pipeline", "audit-verify"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.output


def test_cli_screen_prints_table_and_json(monkeypatch):
    monkeypatch.setattr("tradingagents.site.screener_api.screen_korean_market", _fake_screen)
    result = runner.invoke(app, ["screen", "--markets", "KOSPI", "--top", "3"])
    assert result.exit_code == 0, result.output
    assert "005930" in result.output
    result = runner.invoke(app, ["screen", "--markets", "KOSPI", "--json"])
    assert result.exit_code == 0, result.output
    assert "screening_only_no_orders" in result.output


def test_cli_forecast_uses_history(monkeypatch):
    monkeypatch.setattr("tradingagents.site.screener_api._default_history_fetcher", lambda vendor: (lambda c, s, e: _points()))
    result = runner.invoke(app, ["forecast", "005930", "--horizon", "5", "--date", "2026-09-05"])
    assert result.exit_code == 0, result.output
    assert "naive" in result.output


def test_cli_playbook_list():
    result = runner.invoke(app, ["playbook", "x", "--list"])
    assert result.exit_code == 0, result.output
    assert "market_analysis" in result.output
    assert "global_events" in result.output


def test_cli_pipeline_dry_run_with_deterministic_confirmer(monkeypatch, tmp_path):
    def fake_snapshot(when, markets):
        return MarketSnapshot(
            as_of_date="2026-09-05",
            markets=tuple(markets),
            rows=[MarketSnapshotRow("005930", "삼성전자", "KOSPI", 70_000.0, 1e7, 5e11, 4e14, 0.5, 12.0, 1.2, 2.0)],
        )

    monkeypatch.setattr("tradingagents.screener.screener.load_market_snapshot", fake_snapshot)
    monkeypatch.setattr("tradingagents.screener.screener._chart_history_fetcher", lambda code, s, e: _points())
    monkeypatch.setattr("tradingagents.harness.pipeline._chart_history_fetcher", lambda code, s, e: _points())
    output = tmp_path / "run.json"
    result = runner.invoke(
        app,
        ["pipeline", "--markets", "KOSPI", "--confirmer", "none", "--audit-log", str(tmp_path / "audit.jsonl"), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["execution_boundary"] == "dry_run_no_orders"
    assert payload["decisions"][0]["code"] == "005930"
    verify = runner.invoke(app, ["audit-verify", "--path", str(tmp_path / "audit.jsonl")])
    assert verify.exit_code == 0, verify.output
    assert "OK" in verify.output


def test_cli_pipeline_rejects_bad_options():
    result = runner.invoke(app, ["pipeline", "--confirmer", "magic"])
    assert result.exit_code != 0
    result = runner.invoke(app, ["pipeline", "--broker", "robinhood", "--confirmer", "none"])
    assert result.exit_code != 0


def test_cli_audit_verify_reports_broken_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"sequence": 1, "timestamp": "t", "event_type": "x", "payload": {}, "previous_hash": "bad", "hash": "bad"}\n', encoding="utf-8")
    result = runner.invoke(app, ["audit-verify", "--path", str(path)])
    assert result.exit_code == 1
    assert "BROKEN" in result.output

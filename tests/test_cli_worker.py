from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def test_cli_exposes_analysis_request_worker_help():
    result = runner.invoke(app, ["process-analysis-requests", "--help"])

    assert result.exit_code == 0
    assert "Process queued site analysis refresh requests" in result.output
    assert "--dry-run" in result.output


def test_cli_worker_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    result = runner.invoke(app, ["process-analysis-requests", "--dry-run"])

    assert result.exit_code != 0
    assert "DATABASE_URL is required" in result.output

from tradingagents.ops.korea_doctor import format_results, has_failures, run_korea_market_checks


def test_korea_doctor_passes_configured_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai")
    monkeypatch.setenv("DART_API_KEY", "dart")
    monkeypatch.setenv("NAVER_CLIENT_ID", "naver-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "naver-secret")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_ACCOUNT_PRODUCT_CODE", "01")
    monkeypatch.setenv("KIS_APP_KEY", "kis-key")
    monkeypatch.setenv("KIS_APP_SECRET", "kis-secret")
    monkeypatch.setenv("KIS_IS_PAPER", "true")

    results = run_korea_market_checks()

    assert not has_failures(results)
    report = format_results(results)
    assert "[PASS] KIS config" in report
    assert "kis-secret" not in report


def test_korea_doctor_reports_bad_ca_bundle(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_HTTP_CA_BUNDLE", "Z:/missing/cert.pem")

    results = run_korea_market_checks()

    assert any(result.name == "HTTPS CA bundle" and result.status == "FAIL" for result in results)


def test_korea_doctor_warns_when_ssl_verification_is_disabled(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_HTTP_VERIFY_SSL", "false")

    results = run_korea_market_checks()

    assert any(result.name == "HTTPS verification" and result.status == "WARN" for result in results)
    assert not has_failures([result for result in results if result.name == "HTTPS verification"])


def test_korea_doctor_reports_database_url_without_exposing_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example.supabase.co:5432/postgres")

    results = run_korea_market_checks()
    report = format_results(results)

    assert any(result.name == "DATABASE_URL" and result.status == "PASS" for result in results)
    assert "secret" not in report
    assert "example.supabase.co" not in report


def test_korea_doctor_requires_database_url_when_storage_enabled(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_STORAGE_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    results = run_korea_market_checks()

    assert any(result.name == "analysis storage" and result.status == "FAIL" for result in results)


def test_korea_doctor_reports_enabled_analysis_storage(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_STORAGE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example.supabase.co:5432/postgres")

    results = run_korea_market_checks()
    report = format_results(results)

    assert any(result.name == "analysis storage" and result.status == "PASS" for result in results)
    assert "secret" not in report


def test_korea_doctor_validates_analysis_user_id(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_USER_ID", "not-a-uuid")

    results = run_korea_market_checks()

    assert any(result.name == "analysis user" and result.status == "FAIL" for result in results)

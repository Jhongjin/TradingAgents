import pandas as pd

from tradingagents.dataflows import krx_openapi
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.ops import korea_doctor
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


def test_korea_doctor_skips_krx_online_probe_by_default(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "krx-key")

    results = run_korea_market_checks()

    assert any(result.name == "KRX Open API probe" and result.status == "SKIP" for result in results)


def test_korea_doctor_reports_matching_krx_key_aliases(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("KRX_OPENAPI_KEY", "krx-key")

    results = run_korea_market_checks()

    assert any(
        result.name == "KRX_API_KEY"
        and result.status == "PASS"
        and "both aliases match" in result.detail
        for result in results
    )


def test_korea_doctor_warns_when_krx_key_aliases_differ(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "primary-key")
    monkeypatch.setenv("KRX_OPENAPI_KEY", "alias-key")

    results = run_korea_market_checks()

    assert any(
        result.name == "KRX_API_KEY"
        and result.status == "WARN"
        and "different values" in result.detail
        for result in results
    )


def test_korea_doctor_warns_when_krx_key_has_outer_whitespace(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", " krx-key ")

    results = run_korea_market_checks()

    assert any(
        result.name == "KRX_API_KEY"
        and result.status == "WARN"
        and "whitespace" in result.detail
        for result in results
    )


def test_korea_doctor_reports_krx_online_probe_failure(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("TRADINGAGENTS_DOCTOR_CHECK_KRX_ONLINE", "true")
    monkeypatch.setenv("TRADINGAGENTS_KRX_PROBE_TICKER", "086520")

    def fail_probe(*args, **kwargs):
        raise VendorUnavailableError("Invalid API key (401 Unauthorized)")

    captured = {}

    def raw_detail(symbol, probe_date):
        captured["symbol"] = symbol
        return "KRX raw response=Unauthorized API Call"

    monkeypatch.setattr(krx_openapi, "get_ohlcv_frame", fail_probe)
    monkeypatch.setattr("tradingagents.ops.korea_doctor._krx_raw_unauthorized_detail", raw_detail)

    results = run_korea_market_checks()

    assert any(
        result.name == "KRX Open API probe"
        and result.status == "FAIL"
        and "Invalid API key" in result.detail
        for result in results
    )
    assert captured["symbol"] == "086520"
    assert "Unauthorized API Call" in format_results(results)


def test_korea_doctor_maps_kosdaq_probe_to_kosdaq_krx_endpoint(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "krx-key")

    assert korea_doctor._krx_daily_trade_endpoint("086520") == "ksq_bydd_trd"
    assert korea_doctor._krx_endpoint_label("ksq_bydd_trd") == "코스닥 일별매매정보"


def test_korea_doctor_reports_krx_online_probe_success(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    monkeypatch.setenv("TRADINGAGENTS_DOCTOR_CHECK_KRX_ONLINE", "true")
    monkeypatch.setenv("TRADINGAGENTS_DOCTOR_KRX_PROBE_DATE", "2026-05-04")
    monkeypatch.setattr(
        krx_openapi,
        "get_ohlcv_frame",
        lambda *args, **kwargs: pd.DataFrame({"Close": [70500]}, index=[pd.Timestamp("2026-05-04")]),
    )

    results = run_korea_market_checks()

    assert any(result.name == "KRX Open API probe" and result.status == "PASS" for result in results)


def test_korea_doctor_validates_analysis_user_id(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_USER_ID", "not-a-uuid")

    results = run_korea_market_checks()

    assert any(result.name == "analysis user" and result.status == "FAIL" for result in results)

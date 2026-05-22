from tradingagents.report_quality import enrich_reports_with_quality, evaluate_report_quality


def test_evaluate_report_quality_marks_grounded_report_low_risk():
    run = {"ticker_code": "005930", "ticker_name": "삼성전자", "trade_date": "2026-05-05"}
    report = {
        "role": "market",
        "title": "삼성전자 market",
        "content": "2026-05-05 기준 KRX OHLCV와 거래량을 확인했습니다. 삼성전자 005930 수급은 중립입니다.",
    }

    quality = evaluate_report_quality(report, run)

    assert quality["status"] == "pass"
    assert quality["risk_level"] == "low"
    assert quality["failed_count"] == 0
    assert quality["warning_count"] == 0


def test_evaluate_report_quality_flags_unsafe_execution_claims():
    run = {"ticker_code": "005930", "ticker_name": "삼성전자", "trade_date": "2026-05-05"}
    report = {
        "role": "market",
        "title": "Market",
        "content": "무조건 상승합니다. 주문 실행 완료.",
    }

    quality = evaluate_report_quality(report, run)

    assert quality["status"] == "review"
    assert quality["risk_level"] == "high"
    assert quality["failed_count"] == 1
    assert any(check["id"] == "execution_boundary" and check["status"] == "fail" for check in quality["checks"])


def test_enrich_reports_with_quality_preserves_existing_metadata():
    run = {"ticker_code": "005930", "ticker_name": "삼성전자", "trade_date": "2026-05-05"}
    reports = [
        {
            "role": "news",
            "content": "2026-05-05 기준 Naver 뉴스에서 삼성전자 005930 관련 기사를 확인했습니다.",
            "metadata_json": {"source": "test"},
        }
    ]

    enriched = enrich_reports_with_quality(reports, run)

    assert enriched[0]["metadata_json"]["source"] == "test"
    assert enriched[0]["quality_checks"]["risk_level"] == "low"
    assert enriched[0]["metadata_json"]["quality_checks"]["risk_level"] == "low"

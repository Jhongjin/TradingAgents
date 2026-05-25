"""Heuristic grounding checks for generated analysis reports."""

from __future__ import annotations

from typing import Any


_CERTAINTY_TERMS = (
    "guaranteed",
    "definitely",
    "risk-free",
    "cannot lose",
    "무조건",
    "확실히",
    "보장",
    "손실이 없다",
)
_EXECUTION_TERMS = (
    "order placed",
    "executed order",
    "we bought",
    "we sold",
    "주문 실행",
    "매매 실행",
    "자동매매",
    "실거래 완료",
)
_COMMON_SOURCE_TERMS = (
    "krx",
    "pykrx",
    "ohlcv",
    "dart",
    "naver",
    "공시",
    "뉴스",
    "재무",
    "거래량",
    "벤치마크",
)
_ROLE_SOURCE_TERMS = {
    "market": ("krx", "pykrx", "ohlcv", "가격", "거래량", "수급", "benchmark", "벤치마크"),
    "social": ("naver", "뉴스", "sentiment", "심리", "기사"),
    "news": ("naver", "뉴스", "기사", "공시", "보도"),
    "fundamentals": ("dart", "공시", "재무", "매출", "이익", "현금흐름"),
}


def enrich_reports_with_quality(reports: list[dict[str, Any]], run: dict[str, Any]) -> list[dict[str, Any]]:
    """Return report copies with non-secret grounding checks attached."""

    enriched = []
    for report in reports:
        item = dict(report)
        metadata = dict(item.get("metadata_json") or item.get("metadata") or {})
        quality = metadata.get("quality_checks") or evaluate_report_quality(item, run)
        metadata["quality_checks"] = quality
        item["metadata_json"] = metadata
        item["quality_checks"] = quality
        enriched.append(item)
    return enriched


def evaluate_report_quality(report: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether an LLM report is anchored to the saved analysis context.

    This is intentionally deterministic and conservative. It is not a truth
    oracle; it surfaces missing anchors and unsafe claims for human review.
    """

    role = str(report.get("role") or "agent").lower()
    content = str(report.get("content") or "")
    title = str(report.get("title") or "")
    text = f"{title}\n{content}"
    normalized = text.lower()
    ticker_code = str(run.get("ticker_code") or "")
    ticker_name = str(run.get("ticker_name") or "")
    trade_date = str(run.get("trade_date") or "")
    source_terms = _ROLE_SOURCE_TERMS.get(role, _COMMON_SOURCE_TERMS)

    checks = [
        _check(
            "ticker_anchor",
            "종목 기준",
            bool((ticker_code and ticker_code in text) or (ticker_name and ticker_name in text)),
            f"{ticker_name or ticker_code or 'ticker'}가 본문에 명시되어야 합니다.",
        ),
        _check(
            "date_anchor",
            "기준일",
            bool(trade_date and (trade_date in text or trade_date[:4] in text or "기준" in text)),
            f"데이터 기준일 {trade_date or '-'}를 본문 또는 기준 문구로 연결해야 합니다.",
        ),
        _check(
            "source_anchor",
            "출처 근거",
            _contains_any(normalized, source_terms),
            "역할에 맞는 데이터 출처(KRX/DART/Naver/뉴스/공시/거래량 등)가 필요합니다.",
        ),
        _check(
            "certainty_guard",
            "확정 표현",
            not _contains_any(normalized, _CERTAINTY_TERMS),
            "확정 수익, 무위험, 보장 표현은 검토가 필요합니다.",
        ),
        _check(
            "execution_boundary",
            "주문 경계",
            not _contains_any(normalized, _EXECUTION_TERMS),
            "리포트가 실제 주문 실행을 암시하면 안 됩니다.",
            fail_when_missing=True,
        ),
    ]
    passed_count = sum(1 for check in checks if check["status"] == "pass")
    warning_count = sum(1 for check in checks if check["status"] == "warn")
    failed_count = sum(1 for check in checks if check["status"] == "fail")
    risk_level = "high" if failed_count else "medium" if warning_count >= 2 else "low"
    return {
        "status": "pass" if risk_level == "low" else "review",
        "risk_level": risk_level,
        "score": passed_count / len(checks),
        "passed_count": passed_count,
        "warning_count": warning_count,
        "failed_count": failed_count,
        "total_count": len(checks),
        "checks": checks,
        "warnings": [check["detail"] for check in checks if check["status"] != "pass"],
    }


def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: str,
    *,
    fail_when_missing: bool = False,
) -> dict[str, str]:
    if passed:
        return {"id": check_id, "label": label, "status": "pass", "detail": "확인됨"}
    return {"id": check_id, "label": label, "status": "fail" if fail_when_missing else "warn", "detail": detail}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)

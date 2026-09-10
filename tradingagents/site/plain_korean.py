"""Plain-Korean labels for machine wording that reaches readers.

The pipeline records its reasons and order states in English shorthand
("dry run, no fill", "expected return +2.10% below +3.00%") and stores
"UNKNOWN" when a market could not be resolved. Those strings are useful in the
audit log and unreadable on a page, so every reader-facing view runs them
through here instead of printing them raw.
"""

from __future__ import annotations

import re
from typing import Any

ORDER_STATUS_LABELS = {
    "dry_run": "모의 주문 · 체결 없음",
    "filled": "체결 완료",
    "accepted": "주문 접수",
    "rejected": "주문 거부",
    "skipped": "주문 건너뜀",
}

EXIT_REASON_LABELS = {
    "stop_loss": "손절선 도달",
    "take_profit": "목표가 도달",
    "max_holding_days": "보유 기간 종료",
    "news_risk": "악재 감지",
    "paper fill": "모의 체결",
}

STAGE_HINTS = {
    "screened": "규칙 점수만 통과",
    "forecast_rejected": "예측 기준 미달",
    "confirmation_rejected": "AI 판정에서 제외",
    "sized": "수량 계산 단계",
    "gate_rejected": "위험 한도에서 제외",
    "ordered": "모의 주문 기록",
    "exit": "청산 기록",
}

_PERCENT = r"([+-]?[\d.,]+%)"
_NUMBER = r"([\d.,]+)"
_PERCENT_LOOSE = r"([\d.,]+%)"

_REASON_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^dry run, no fill$", re.I), "실제 주문 없이 기록만 남겼습니다"),
    (re.compile(rf"^expected return {_PERCENT} below {_PERCENT}$", re.I), "기대 수익률 \\1로 기준 \\2에 못 미쳤습니다"),
    (re.compile(rf"^probability up {_PERCENT} below {_PERCENT}$", re.I), "상승 확률 \\1로 기준 \\2에 못 미쳤습니다"),
    (re.compile(r"^confirmer rating (.+) is not bullish$", re.I), "AI 판정이 '\\1'이라 매수 의견이 아닙니다"),
    (re.compile(rf"^confidence {_NUMBER} below {_NUMBER}$", re.I), "AI 확신도 \\1로 기준 \\2에 못 미쳤습니다"),
    (re.compile(r"^insufficient history$", re.I), "가격 이력이 부족합니다"),
    (re.compile(r"^history unavailable: (.+)$", re.I), "가격 이력을 불러오지 못했습니다"),
    (re.compile(r"^forecast unavailable$", re.I), "예측값을 만들지 못했습니다"),
    (re.compile(r"^sizing produced zero quantity$", re.I), "매수 수량이 0으로 계산됐습니다"),
    (re.compile(r"^sizing failed: (.+)$", re.I), "수량 계산에 실패했습니다"),
    (re.compile(r"^no confirmer configured \(fail closed\)$", re.I), "AI 확인 단계가 꺼져 있어 보류했습니다"),
    (re.compile(r"^confirmer error \(fail closed\): (.+)$", re.I), "AI 확인 중 오류가 나서 보류했습니다"),
    (re.compile(r"^kill switch active$", re.I), "긴급 정지가 켜져 있습니다"),
    (re.compile(r"^(.+) is not in the allowed instrument set$", re.I), "허용된 종목 목록에 없습니다"),
    (re.compile(r"^outside regular trading session$", re.I), "정규장 시간이 아닙니다"),
    (re.compile(rf"^daily order cap {_NUMBER} reached$", re.I), "하루 주문 한도 \\1건을 채웠습니다"),
    (re.compile(rf"^daily loss {_PERCENT} exceeds limit {_PERCENT}$", re.I), "당일 손실 \\1이 한도 \\2를 넘었습니다"),
    (re.compile(rf"^order notional {_NUMBER} exceeds {_NUMBER}$", re.I), "주문 금액 \\1원이 한도 \\2원을 넘었습니다"),
    (re.compile(rf"^projected weight {_PERCENT} exceeds {_PERCENT}$", re.I), "예상 비중 \\1이 한도 \\2를 넘었습니다"),
    (re.compile(r"^gross exposure limit exceeded$", re.I), "총 노출 한도를 넘었습니다"),
    (re.compile(rf"^position count would exceed {_NUMBER}$", re.I), "보유 종목 수가 한도 \\1개를 넘습니다"),
    (re.compile(rf"^sector (.+) already holds {_NUMBER} of {_NUMBER}$", re.I), "\\1 업종을 이미 \\2종목 보유해 한도 \\3종목에 걸렸습니다"),
    (re.compile(rf"^foreign and institutional flow is net selling over {_NUMBER} days$", re.I), "최근 \\1거래일 외국인·기관이 순매도했습니다"),
    (re.compile(r"^insufficient cash$", re.I), "예수금이 모자랍니다"),
    (re.compile(rf"^cash reserve {_PERCENT_LOOSE} reached; no new entries today$", re.I), "현금을 \\1 남겨 두는 규칙에 걸려 오늘은 새로 담지 않았습니다"),
    (re.compile(r"^short selling is not allowed$", re.I), "공매도는 허용하지 않습니다"),
)


def exit_reason_label(reason: Any) -> str:
    """Why a simulated position was closed."""

    key = str(reason or "").strip()
    if not key:
        return "정리"
    return EXIT_REASON_LABELS.get(key.lower(), reason_label(key))


def order_status_label(status: Any) -> str:
    """Reader-facing wording for a broker order state."""

    key = str(status or "").strip().lower()
    if not key:
        return "-"
    return ORDER_STATUS_LABELS.get(key, key)


def reason_label(text: Any) -> str:
    """Translate one recorded reason; unknown wording passes through unchanged."""

    raw = str(text or "").strip()
    if not raw:
        return ""
    for pattern, replacement in _REASON_RULES:
        if pattern.match(raw):
            return pattern.sub(replacement, raw)
    return raw


def reason_text(reasons: Any, *, limit: int = 3, separator: str = " · ") -> str:
    """Join the first few reasons as one readable line."""

    if not reasons:
        return ""
    items = [reason_label(item) for item in list(reasons)[:limit]]
    return separator.join(item for item in items if item)


def market_label(market: Any, ticker_code: Any = None) -> str:
    """KOSPI/KOSDAQ for a row, resolving or dropping an unresolved market.

    Runs stored before the ticker directory existed carry "UNKNOWN"; the
    directory usually knows the market, and when it does not the badge is
    dropped rather than showing a placeholder to the reader.
    """

    value = str(market or "").strip().upper()
    if value and value not in {"UNKNOWN", "KR", "NONE", "NULL", "-"}:
        return value
    code = str(ticker_code or "").strip()
    if not code:
        return ""
    try:
        from tradingagents.dataflows.kr_ticker_directory import lookup_directory

        entry = lookup_directory(code)
    except Exception:
        return ""
    resolved = str(getattr(entry, "market", "") or "").strip().upper() if entry else ""
    return resolved if resolved and resolved != "UNKNOWN" else ""

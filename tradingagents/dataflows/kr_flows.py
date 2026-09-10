"""Who has been buying: foreign and institutional net purchases, and shorting.

Korean retail reads supply and demand before almost anything else, and our
score never looked at it: trend, momentum and traded value only. This exposes
the flow behind a ticker so a pick can say who was on the other side, and so a
gate can require the big money to be buying before we do.

Read-only market data. Nothing here decides or places anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

INVESTOR_LABELS = {
    "foreign": ("외국인합계", "외국인", "Foreign"),
    "institution": ("기관합계", "기관", "Institution"),
    "individual": ("개인", "Individual"),
}


def _compact(value: str) -> str:
    return str(value or "").replace("-", "")[:8]


def _get_pykrx():
    from tradingagents.dataflows.pykrx_vendor import _get_pykrx_stock_module

    return _get_pykrx_stock_module()


def _column_for(frame: Any, group: str) -> str | None:
    for name in INVESTOR_LABELS.get(group, ()):
        if name in getattr(frame, "columns", []):
            return name
    for name in INVESTOR_LABELS.get(group, ()):
        for column in getattr(frame, "columns", []):
            if name in str(column):
                return column
    return None


def get_investor_flow(ticker: str, *, days: int = 5, end_date: str | None = None) -> dict[str, Any]:
    """Net purchase value per investor group over the recent window.

    Returns ``{"status": ..., "foreign_net": .., "institution_net": .., "days": n}``
    with values in KRW. A blocked or empty vendor gives ``status`` other than
    ``available`` and no numbers, never a guess.
    """

    code = str(ticker or "").strip()
    if len(code) != 6 or not code.isdigit():
        return {"status": "unsupported", "ticker_code": code}
    end = datetime.strptime(end_date[:10], "%Y-%m-%d") if end_date else datetime.now()
    start = end - timedelta(days=max(days, 1) * 2 + 5)
    try:
        stock = _get_pykrx()
        frame = stock.get_market_trading_value_by_date(_compact(start.strftime("%Y-%m-%d")), _compact(end.strftime("%Y-%m-%d")), code)
    except Exception as exc:
        return {"status": "unavailable", "ticker_code": code, "error": f"{exc.__class__.__name__}: {exc}"}
    if frame is None or getattr(frame, "empty", True):
        return {"status": "empty", "ticker_code": code}

    recent = frame.sort_index().tail(max(days, 1))
    result: dict[str, Any] = {"status": "available", "ticker_code": code, "days": int(len(recent))}
    for group in ("foreign", "institution", "individual"):
        column = _column_for(recent, group)
        if column is None:
            continue
        try:
            total = float(recent[column].sum())
        except Exception:
            continue
        result[f"{group}_net"] = total
        result[f"{group}_buying_days"] = int((recent[column] > 0).sum())
    return result


def flow_summary(flow: dict[str, Any] | None) -> str:
    """One Korean line about the flow, or "" when there is nothing to say."""

    if not flow or flow.get("status") != "available":
        return ""
    parts = []
    for group, label in (("foreign", "외국인"), ("institution", "기관")):
        value = flow.get(f"{group}_net")
        if value is None:
            continue
        billions = value / 100_000_000
        if abs(billions) < 0.5:
            continue
        direction = "순매수" if billions > 0 else "순매도"
        parts.append(f"{label} {abs(billions):,.0f}억 {direction}")
    if not parts:
        return ""
    return f"최근 {flow.get('days')}거래일 " + ", ".join(parts)

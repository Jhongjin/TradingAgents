"""Copy what the paper account holds into a member's own trade journal.

The account and the journal already exist separately; this is the bridge a
reader asks for after seeing a holding they like. Only positions the member is
allowed to see are copied, so a free member copies the settled ones and a
subscriber copies today's too. Nothing here places an order: it writes the same
rows the member could type by hand.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from tradingagents.storage import ManualTradeInput, StorageRepository

JOURNAL_NAME = "AI 모의 계좌 따라하기"


def _as_date(value: Any) -> date | None:
    text = str(value or "")[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except Exception:
        return None


def copy_account_holdings(repo: StorageRepository, *, user_id: str, positions: list[Mapping[str, Any]], journal_name: str = JOURNAL_NAME) -> dict[str, Any]:
    """Add each holding to the member's journal, skipping ones already there."""

    if not positions:
        return {"status": "nothing_to_copy", "copied": 0, "skipped": 0}

    existing = next((row for row in repo.list_manual_portfolios(user_id=user_id, limit=50) if str(row.get("name")) == journal_name), None)
    portfolio_id = str(existing["id"]) if existing else repo.create_manual_portfolio(user_id=user_id, name=journal_name)
    already = {str(trade.get("ticker_code")) for trade in repo.manual_trades_for_portfolio(portfolio_id)}

    copied = skipped = 0
    for position in positions:
        code = str(position.get("ticker_code") or "").strip()
        quantity = int(position.get("quantity") or 0)
        price = _money(position.get("average_price"))
        if not code or quantity <= 0 or price is None:
            skipped += 1
            continue
        if code in already:
            skipped += 1
            continue
        repo.add_manual_trade(
            ManualTradeInput(
                portfolio_id=portfolio_id,
                ticker_code=code,
                ticker_name=position.get("ticker_name"),
                side="buy",
                trade_date=_as_date(position.get("entry_date")) or datetime.now().date(),
                price=price,
                quantity=Decimal(quantity),
                memo="AI 모의 계좌에서 담음",
            )
        )
        target = _money(position.get("target_price"))
        stop = _money(position.get("stop_price"))
        if target is not None or stop is not None:
            repo.set_price_target(portfolio_id=portfolio_id, ticker_code=code, target_price=target, stop_price=stop, memo="AI 모의 계좌 기준")
        already.add(code)
        copied += 1

    return {
        "status": "copied" if copied else "nothing_to_copy",
        "portfolio_id": portfolio_id,
        "portfolio_name": journal_name,
        "copied": copied,
        "skipped": skipped,
    }

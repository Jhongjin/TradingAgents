"""The digest lists companies, not rows.

Two books run the same strategy side by side, so nearly every exit appears
twice. Listing the rows flat made five companies read as eleven losses.
"""

from tradingagents.site.weekly_report import compose_weekly_message, group_closed_by_ticker

CLOSED = [
    {"ticker_code": "041510", "ticker_name": "에스엠", "quantity": 55, "entry_price": 88_600.0,
     "exit_reason": "stop_loss", "realized_pnl": -422_090.0, "realized_return": -0.0866,
     "account_label": "AI 확인"},
    {"ticker_code": "041510", "ticker_name": "에스엠", "quantity": 54, "entry_price": 88_800.0,
     "exit_reason": "stop_loss", "realized_pnl": -425_216.0, "realized_return": -0.0887,
     "account_label": "규칙 전용"},
    {"ticker_code": "095340", "ticker_name": "ISC", "quantity": 26, "entry_price": 190_600.0,
     "exit_reason": "stop_loss", "realized_pnl": -298_634.0, "realized_return": -0.0603,
     "account_label": "규칙 전용"},
    {"ticker_code": "010170", "ticker_name": "대한광통신", "quantity": 3, "entry_price": 16_340.0,
     "exit_reason": "take_profit", "realized_pnl": 6_031.0, "realized_return": 0.1230,
     "account_label": "규칙 전용"},
]


def test_a_company_held_in_both_books_is_one_line():
    grouped = group_closed_by_ticker(CLOSED)
    assert len(grouped) == 3
    sm = next(row for row in grouped if row["code"] == "041510")
    assert sm["books"] == 2


def test_won_amounts_add_up_and_the_percentage_does_not():
    """Both positions are real, so the money adds; the rate must not."""

    sm = next(row for row in group_closed_by_ticker(CLOSED) if row["code"] == "041510")
    assert sm["realized_pnl"] == -847_306.0
    # each book lost about 8.7%; the pair must still read about 8.7%
    assert -0.09 < sm["realized_return"] < -0.085


def test_the_biggest_mover_comes_first():
    codes = [row["code"] for row in group_closed_by_ticker(CLOSED)]
    assert codes[0] == "041510"


def test_a_win_is_not_dropped_for_being_small():
    grouped = group_closed_by_ticker(CLOSED)
    assert any(row["code"] == "010170" and row["realized_pnl"] > 0 for row in grouped)


def test_the_message_says_both_counts_so_nothing_looks_hidden():
    message = compose_weekly_message({
        "from": "2026-09-11", "to": "2026-09-18", "books": [],
        "closed": CLOSED, "open_count": 18, "site_base_url": "https://example.test",
    })
    assert "정리한 종목 3개" in message
    assert "합쳐 4건" in message          # the row count is still stated
    assert "두 계좌" in message
    assert message.count("에스엠") == 1   # and the company appears once


def test_one_book_only_does_not_get_the_two_account_note():
    single = [row for row in CLOSED if row["account_label"] == "규칙 전용"]
    message = compose_weekly_message({
        "from": "2026-09-11", "to": "2026-09-18", "books": [],
        "closed": single, "open_count": 5, "site_base_url": "https://example.test",
    })
    assert "합쳐" not in message
    assert "두 계좌" not in message


def test_nothing_closed_still_reads_as_a_sentence():
    message = compose_weekly_message({
        "from": "2026-09-11", "to": "2026-09-18", "books": [],
        "closed": [], "open_count": 0, "site_base_url": "https://example.test",
    })
    assert "정리된 종목은 없습니다" in message

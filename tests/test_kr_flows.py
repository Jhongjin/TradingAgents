"""Investor flow: who was buying, and the optional gate that requires it."""

import pandas as pd
import pytest

from tradingagents.dataflows import kr_flows


class _Stock:
    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def get_market_trading_value_by_date(self, start, end, code):
        self.calls += 1
        return self.frame


def _frame(foreign, institution):
    return pd.DataFrame(
        {"외국인합계": foreign, "기관합계": institution, "개인": [-(a + b) for a, b in zip(foreign, institution)]},
        index=pd.date_range("2026-09-01", periods=len(foreign)),
    )


def test_flow_sums_the_recent_window(monkeypatch):
    stock = _Stock(_frame([1_000_000_000] * 6, [-200_000_000] * 6))
    monkeypatch.setattr(kr_flows, "_get_pykrx", lambda: stock)

    flow = kr_flows.get_investor_flow("005930", days=5)
    assert flow["status"] == "available" and flow["days"] == 5
    assert flow["foreign_net"] == 5_000_000_000 and flow["institution_net"] == -1_000_000_000
    assert flow["foreign_buying_days"] == 5 and flow["institution_buying_days"] == 0
    assert kr_flows.flow_summary(flow) == "최근 5거래일 외국인 50억 순매수, 기관 10억 순매도"


def test_an_unreachable_vendor_reports_instead_of_guessing(monkeypatch):
    def _explode():
        raise RuntimeError("KRX blocked")

    monkeypatch.setattr(kr_flows, "_get_pykrx", _explode)
    flow = kr_flows.get_investor_flow("005930")
    assert flow["status"] == "unavailable" and "foreign_net" not in flow
    assert kr_flows.flow_summary(flow) == ""

    monkeypatch.setattr(kr_flows, "_get_pykrx", lambda: _Stock(pd.DataFrame()))
    assert kr_flows.get_investor_flow("005930")["status"] == "empty"
    assert kr_flows.get_investor_flow("abc")["status"] == "unsupported"


def test_a_quiet_flow_says_nothing():
    assert kr_flows.flow_summary({"status": "available", "days": 5, "foreign_net": 10_000_000}) == ""
    assert kr_flows.flow_summary(None) == ""


def test_the_flow_gate_is_off_until_it_is_turned_on():
    from tradingagents.harness.pipeline import PipelineConfig

    assert PipelineConfig().require_positive_flow is False

    from tradingagents.site.plain_korean import reason_label

    assert reason_label("foreign and institutional flow is net selling over 5 days") == "최근 5거래일 외국인·기관이 순매도했습니다"


def test_the_switch_is_published_with_the_other_rules():
    from tradingagents.site.paper_rules import build_rules_payload, format_rule

    assert format_rule("require_positive_flow", False) == "미사용"
    assert format_rule("require_positive_flow", True) == "사용"
    payload = build_rules_payload([{"as_of_date": "2026-09-10", "metadata": {"config": {"require_positive_flow": False}}}])
    assert any(item["label"] == "수급 조건" and item["value"] == "미사용" for item in payload["current"])

import json

import pytest

from tradingagents.execution import (
    AuditLedger,
    KISBrokerAdapter,
    KISClient,
    KISConfig,
    KISError,
    KoreaTradingRules,
    LiveTradingDisabledError,
    MandateContext,
    MandateGate,
    OrderIntent,
    OrderSide,
    PaperBroker,
    PaperBrokerAdapter,
    PositionSizeRequest,
    RiskLimits,
    TradingMandate,
    size_position,
    stop_from_atr,
)
from tradingagents.execution.kis_client import LIVE_BASE_URL, PAPER_BASE_URL


# ------------------------------------------------------------------ sizing
def test_size_position_uses_risk_budget_as_binding_constraint():
    plan = size_position(PositionSizeRequest("005930", equity=10_000_000, entry_price=70_000, stop_price=66_500))
    assert plan.quantity == 28
    assert plan.binding_constraint == "risk_budget"
    assert plan.risk_percent == pytest.approx(0.0098)


def test_size_position_caps_by_weight_and_cash():
    plan = size_position(
        PositionSizeRequest("005930", equity=10_000_000, entry_price=70_000, stop_price=69_900, max_position_weight=0.1)
    )
    assert plan.binding_constraint == "max_position_weight"
    assert plan.notional <= 1_000_000
    plan = size_position(
        PositionSizeRequest("005930", equity=10_000_000, entry_price=70_000, stop_price=69_900, available_cash=100_000)
    )
    assert plan.binding_constraint == "available_cash"
    assert plan.quantity == 1


def test_size_position_flags_zero_quantity_and_low_reward_risk():
    plan = size_position(
        PositionSizeRequest("005930", equity=100_000, entry_price=70_000, stop_price=35_000, take_profit_price=72_000)
    )
    assert plan.quantity == 0
    assert any("리스크 예산" in note for note in plan.notes)
    plan = size_position(
        PositionSizeRequest("005930", equity=10_000_000, entry_price=70_000, stop_price=66_500, take_profit_price=72_000)
    )
    assert plan.reward_risk_ratio < 1.5
    assert any("손익비" in note for note in plan.notes)


def test_size_position_validation_and_atr_stop():
    with pytest.raises(ValueError):
        PositionSizeRequest("A", equity=1000, entry_price=100, stop_price=100)
    with pytest.raises(ValueError):
        PositionSizeRequest("A", equity=1000, entry_price=100, stop_price=90, risk_percent_per_trade=0.5)
    assert stop_from_atr(100, 2, multiplier=2) == 96
    assert stop_from_atr(100, 80) == 50


# ----------------------------------------------------------------- mandate
def _context(**overrides):
    base = dict(equity=10_000_000, cash=5_000_000, positions={"000660": 2_000_000}, price=70_000)
    base.update(overrides)
    return MandateContext(**base)


def test_mandate_gate_approves_reasonable_buy():
    decision = MandateGate(TradingMandate()).evaluate(OrderIntent("005930", OrderSide.BUY, 10), _context())
    assert decision.approved
    assert decision.reasons == []
    assert decision.checks["position_weight"]


def test_mandate_gate_rejects_weight_cash_count_and_kill_switch():
    gate = MandateGate(TradingMandate(max_position_weight=0.05))
    decision = gate.evaluate(OrderIntent("005930", OrderSide.BUY, 10), _context())
    assert not decision.approved
    assert any("projected weight" in reason for reason in decision.reasons)

    gate = MandateGate(TradingMandate())
    decision = gate.evaluate(OrderIntent("005930", OrderSide.BUY, 100), _context(cash=1_000_000))
    assert "insufficient cash" in decision.reasons

    gate = MandateGate(TradingMandate(max_positions=1))
    decision = gate.evaluate(OrderIntent("005930", OrderSide.BUY, 1), _context())
    assert any("position count" in reason for reason in decision.reasons)

    gate = MandateGate(TradingMandate(kill_switch_active=True))
    decision = gate.evaluate(OrderIntent("005930", OrderSide.BUY, 1), _context())
    assert "kill switch active" in decision.reasons


def test_mandate_gate_daily_loss_blocks_buys_but_allows_sells():
    gate = MandateGate(TradingMandate(max_daily_loss_pct=0.02))
    buy = gate.evaluate(OrderIntent("005930", OrderSide.BUY, 1), _context(realized_pnl_today=-500_000))
    assert not buy.approved
    sell = gate.evaluate(OrderIntent("000660", OrderSide.SELL, 1), _context(realized_pnl_today=-500_000))
    assert sell.approved


def test_mandate_gate_whitelist_blacklist_and_short():
    gate = MandateGate(TradingMandate(instrument_whitelist=("005930",)))
    assert not gate.evaluate(OrderIntent("000660", OrderSide.BUY, 1), _context()).approved
    gate = MandateGate(TradingMandate(instrument_blacklist=("005930",)))
    assert not gate.evaluate(OrderIntent("005930", OrderSide.BUY, 1), _context()).approved
    gate = MandateGate(TradingMandate())
    short = gate.evaluate(OrderIntent("005930", OrderSide.SELL, 1), _context())
    assert "short selling is not allowed" in short.reasons
    with pytest.raises(ValueError):
        TradingMandate(max_positions=0)


# ------------------------------------------------------------------- audit
def test_audit_ledger_chains_and_verifies(tmp_path):
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    first = ledger.append("screen", {"codes": ["005930"]})
    second = ledger.append("order", {"code": "005930", "qty": 3})
    assert first.previous_hash == "0" * 64
    assert second.previous_hash == first.hash
    assert ledger.verify_chain() == (True, None)

    reopened = AuditLedger(tmp_path / "audit.jsonl")
    assert reopened.sequence == 2
    assert reopened.last_hash == second.hash
    third = reopened.append("cycle_complete", {})
    assert third.sequence == 3


def test_audit_ledger_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    ledger = AuditLedger(path)
    ledger.append("order", {"qty": 1})
    ledger.append("order", {"qty": 2})
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["payload"]["qty"] = 99
    lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, error = AuditLedger(path).verify_chain()
    assert not ok
    assert "hash mismatch" in error


def test_audit_ledger_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_AUDIT_LOG_PATH", str(tmp_path / "x.jsonl"))
    assert AuditLedger.from_env().path == tmp_path / "x.jsonl"
    with pytest.raises(ValueError):
        AuditLedger(tmp_path / "y.jsonl").append("", {})


# ------------------------------------------------------------------ brokers
def test_paper_broker_adapter_snapshot_and_orders():
    adapter = PaperBrokerAdapter(
        PaperBroker.with_limits(initial_cash=1_000_000, limits=RiskLimits(max_position_weight=0.5), currency="KRW", execution_rules=KoreaTradingRules())
    )
    dry = adapter.place_order(OrderIntent("005930", OrderSide.BUY, 5), price=70_000, dry_run=True)
    assert dry.status == "dry_run"
    assert adapter.account_snapshot().cash == 1_000_000

    filled = adapter.place_order(OrderIntent("005930", OrderSide.BUY, 5), price=70_000)
    assert filled.status == "filled"
    assert filled.fill.quantity == 5
    snapshot = adapter.account_snapshot({"005930": 71_000})
    assert snapshot.positions["005930"]["quantity"] == 5
    assert snapshot.equity == pytest.approx(1_000_000 - 350_000 + 355_000)

    rejected = adapter.place_order(OrderIntent("005930", OrderSide.BUY, 1_000), price=70_000)
    assert rejected.status == "rejected"
    assert filled.as_dict()["order"]["side"] == "buy"


def _paper_config():
    return KISConfig(account_no="12345678", account_product_code="01", app_key="key", app_secret="secret", is_paper=True)


def _fake_transport(log):
    def transport(method, url, headers, params, json_body):
        log.append({"method": method, "url": url, "headers": dict(headers), "params": params, "json": json_body})
        if url.endswith("/oauth2/tokenP"):
            return {"access_token": "token-1", "expires_in": 86400}
        if "inquire-price" in url:
            return {"rt_cd": "0", "output": {"stck_prpr": "70000", "prdy_ctrt": "1.2", "acml_vol": "1000"}}
        if "inquire-balance" in url:
            return {
                "rt_cd": "0",
                "output1": [{"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "10", "pchs_avg_pric": "68000", "prpr": "70000", "evlu_amt": "700000"}],
                "output2": [{"dnca_tot_amt": "9000000", "tot_evlu_amt": "9700000", "prvs_rcdl_excc_amt": "9000000"}],
            }
        if "order-cash" in url:
            return {"rt_cd": "0", "msg1": "주문 전송 완료", "output": {"ODNO": "0001234", "ORD_TMD": "091500"}}
        raise AssertionError(url)

    return transport


def test_kis_client_uses_paper_domain_and_tr_ids():
    log = []
    client = KISClient(_paper_config(), transport=_fake_transport(log))
    assert client.base_url == PAPER_BASE_URL

    price = client.current_price("005930.KS")
    assert price["price"] == 70_000
    balance = client.balance()
    assert balance["cash"] == 9_000_000
    assert balance["holdings"][0]["code"] == "005930"
    order = client.place_cash_order("005930", OrderSide.BUY, 3, price=70_000)
    assert order["order_id"] == "0001234"

    order_call = [entry for entry in log if "order-cash" in entry["url"]][0]
    assert order_call["headers"]["tr_id"] == "VTTC0802U"
    assert order_call["json"]["ORD_DVSN"] == "00"
    assert order_call["json"]["ORD_UNPR"] == "70000"
    assert order_call["json"]["PDNO"] == "005930"
    balance_call = [entry for entry in log if "inquire-balance" in entry["url"]][0]
    assert balance_call["headers"]["tr_id"] == "VTTC8434R"
    assert sum(1 for entry in log if entry["url"].endswith("/oauth2/tokenP")) == 1


def test_kis_config_prefers_paper_credentials_when_paper(monkeypatch):
    monkeypatch.setenv("KIS_IS_PAPER", "true")
    monkeypatch.setenv("KIS_APP_KEY", "live-key")
    monkeypatch.setenv("KIS_APP_SECRET", "live-secret")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "11111111")
    monkeypatch.setenv("KIS_PAPER_APP_KEY", "paper-key")
    monkeypatch.setenv("KIS_PAPER_APP_SECRET", "paper-secret")
    monkeypatch.setenv("KIS_PAPER_ACCOUNT_NO", "22222222")
    monkeypatch.delenv("KIS_PAPER_ACCOUNT_PRODUCT_CODE", raising=False)
    monkeypatch.setenv("KIS_ACCOUNT_PRODUCT_CODE", "01")
    config = KISConfig.from_env()
    assert config.app_key == "paper-key"
    assert config.account_no == "22222222"
    assert config.account_product_code == "01"  # falls through to the shared value

    monkeypatch.setenv("KIS_IS_PAPER", "false")
    monkeypatch.setenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", "true")
    live = KISConfig.from_env()
    assert live.app_key == "live-key"
    assert live.account_no == "11111111"


def test_kis_client_surfaces_api_errors():
    def transport(method, url, headers, params, json_body):
        if url.endswith("/oauth2/tokenP"):
            return {"access_token": "t", "expires_in": 100}
        return {"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "invalid account"}

    client = KISClient(_paper_config(), transport=transport)
    with pytest.raises(KISError, match="invalid account"):
        client.balance()
    with pytest.raises(ValueError):
        client.place_cash_order("005930", OrderSide.BUY, 0)


def test_kis_adapter_paper_orders_round_to_tick_and_support_dry_run():
    log = []
    adapter = KISBrokerAdapter(KISClient(_paper_config(), transport=_fake_transport(log)), execution_rules=KoreaTradingRules())
    assert adapter.is_paper
    dry = adapter.place_order(OrderIntent("005930", OrderSide.BUY, 2), price=70_010, dry_run=True)
    assert dry.status == "dry_run"
    assert dry.raw["limit_price"] == 70_100
    assert not any("order-cash" in entry["url"] for entry in log)

    accepted = adapter.place_order(OrderIntent("005930", OrderSide.SELL, 2), price=70_010)
    assert accepted.status == "accepted"
    assert accepted.fill.price == 70_000
    snapshot = adapter.account_snapshot()
    assert snapshot.broker == "kis"
    assert snapshot.positions["005930"]["quantity"] == 10
    assert snapshot.raw["mode"] == "paper"


def test_kis_adapter_refuses_live_without_every_gate(monkeypatch):
    live = KISConfig(account_no="12345678", account_product_code="01", app_key="k", app_secret="s", is_paper=False)
    monkeypatch.delenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", raising=False)
    with pytest.raises(LiveTradingDisabledError):
        KISBrokerAdapter(KISClient(live, transport=_fake_transport([])))
    monkeypatch.setenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", "true")
    with pytest.raises(LiveTradingDisabledError):
        KISBrokerAdapter(KISClient(live, transport=_fake_transport([])))
    adapter = KISBrokerAdapter(KISClient(live, transport=_fake_transport([])), confirm_live=True)
    assert not adapter.is_paper
    assert adapter.client.base_url == LIVE_BASE_URL
    assert live.validation_errors() == []
    monkeypatch.setenv("TRADINGAGENTS_ENABLE_LIVE_TRADING", "false")
    assert any("TRADINGAGENTS_ENABLE_LIVE_TRADING" in error for error in live.validation_errors())


def test_kis_config_repr_masks_credentials():
    config = KISConfig(account_no="12345678", account_product_code="01", app_key="real-app-key", app_secret="real-secret", is_paper=True)
    text = f"{config!r} {config}"
    assert "real-app-key" not in text
    assert "real-secret" not in text
    assert "12345678" not in text
    assert "12****78" in text
    assert "is_paper=True" in text

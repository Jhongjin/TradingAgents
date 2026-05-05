from tradingagents.dataflows import interface
from tradingagents.dataflows.errors import VendorUnavailableError


def test_route_to_vendor_falls_back_after_unavailable(monkeypatch):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append("unavailable")
        raise VendorUnavailableError("not configured")

    def available(*args, **kwargs):
        calls.append("available")
        return "ok"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {
            "krx": unavailable,
            "pykrx": available,
        },
    )
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "krx,pykrx")

    assert interface.route_to_vendor("get_stock_data", "005930", "2026-01-01", "2026-01-02") == "ok"
    assert calls == ["unavailable", "available"]


def test_route_to_vendor_reports_last_unavailable(monkeypatch):
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"krx": lambda *args, **kwargs: (_ for _ in ()).throw(VendorUnavailableError("missing key"))},
    )
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "krx")

    try:
        interface.route_to_vendor("get_stock_data", "005930", "2026-01-01", "2026-01-02")
    except RuntimeError as exc:
        assert "missing key" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

import types

from tradingagents.dataflows import http_trust


def test_system_truststore_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_HTTP_USE_SYSTEM_CERTS", "false")
    monkeypatch.setattr(http_trust, "_TRUSTSTORE_APPLIED", False)

    assert http_trust.apply_system_truststore_if_available() is False


def test_system_truststore_injects_when_available(monkeypatch):
    calls = []
    monkeypatch.setenv("TRADINGAGENTS_HTTP_USE_SYSTEM_CERTS", "true")
    monkeypatch.setattr(http_trust, "_TRUSTSTORE_APPLIED", False)
    monkeypatch.setitem(
        __import__("sys").modules,
        "truststore",
        types.SimpleNamespace(inject_into_ssl=lambda: calls.append("inject")),
    )

    assert http_trust.apply_system_truststore_if_available() is True
    assert calls == ["inject"]

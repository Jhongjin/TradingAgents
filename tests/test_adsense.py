"""AdSense: the loader is always present, ad requests are not."""

import pytest

from tradingagents.site.seo import adsense_head, build_ads_txt, normalize_adsense_publisher_id

PUBLISHER = "pub-8052453988928750"


def test_nothing_is_emitted_until_a_publisher_id_exists(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", raising=False)
    assert adsense_head() == ""
    assert normalize_adsense_publisher_id() is None
    assert build_ads_txt() == "# ads.txt is not configured.\n"


def test_the_loader_carries_the_client_and_starts_paused():
    head = adsense_head(PUBLISHER)
    assert f"adsbygoogle.js?client=ca-{PUBLISHER}" in head
    assert 'crossorigin="anonymous"' in head
    # ad requests wait until the browser knows the reader is not on a paid plan
    assert "pauseAdRequests=1" in head and "pauseAdRequests=0" in head
    assert "/api/billing/me" in head and "tradingagents.member.access_token" in head


def test_a_malformed_id_disables_ads_instead_of_breaking_the_page():
    assert adsense_head("not-a-publisher") == ""
    with pytest.raises(ValueError):
        normalize_adsense_publisher_id("not-a-publisher")
    assert adsense_head("ca-" + PUBLISHER).count("ca-" + PUBLISHER) == 1  # the ca- prefix is not doubled


def test_ads_txt_names_google_as_a_direct_seller():
    assert build_ads_txt(adsense_publisher_id=PUBLISHER) == f"google.com, {PUBLISHER}, DIRECT, f08c47fec0942fa0\n"


def test_the_policy_opens_only_when_ads_are_on(monkeypatch):
    from tradingagents.site.api_app import _content_security_policy

    monkeypatch.delenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", raising=False)
    tight = _content_security_policy()
    assert "googlesyndication" not in tight

    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", PUBLISHER)
    open_policy = _content_security_policy()
    for directive in ("script-src", "img-src", "frame-src", "connect-src"):
        section = next(part for part in open_policy.split("; ") if part.startswith(directive))
        assert "googlesyndication" in section or "doubleclick" in section, directive
    assert "frame-ancestors 'none'" in open_policy  # the protections stay
    # the consent platform has to load, or EEA readers see no ads at all
    for directive in ("script-src", "frame-src", "connect-src"):
        section = next(part for part in open_policy.split("; ") if part.startswith(directive))
        assert "fundingchoicesmessages.google.com" in section, directive


def test_every_page_carries_the_loader(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ADSENSE_PUBLISHER_ID", PUBLISHER)
    from tradingagents.site.design_system import render_shell

    html = render_shell(title="t", body="<p>x</p>")
    assert f"client=ca-{PUBLISHER}" in html and "pauseAdRequests" in html


def test_the_privacy_policy_discloses_third_party_ad_cookies():
    """AdSense requires the disclosure, and a reviewer looks for it."""

    from tradingagents.site.web_pages import render_policy_page

    html = render_policy_page("privacy")
    assert "광고와 쿠키" in html
    assert "Google AdSense" in html and "쿠키" in html
    assert "google.com/settings/ads" in html and "aboutads.info" in html
    assert "유료 플랜을 운영하는 기간에는 유료 이용자에게 광고를 게재하지 않으며" in html

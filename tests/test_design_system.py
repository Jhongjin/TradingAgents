from tradingagents.site import design_system as ds


def test_theme_css_defines_every_token_for_every_theme():
    css = ds.theme_css()
    assert css.startswith(":root {")
    assert "@media (prefers-color-scheme: dark) { :root:not([data-theme])" in css
    for theme in ds.THEMES:
        assert f':root[data-theme="{theme}"]' in css
        assert set(ds.THEME_TOKENS[theme]) == set(ds.THEME_TOKENS["light"])
    assert "--accent-soft:" in css and "--glow-b:" in css


def test_sparkline_colors_by_direction_and_handles_short_series():
    up = ds.sparkline_svg([1, 2, 3, 2.5, 4])
    down = ds.sparkline_svg([4, 3, 3.5, 2])
    assert "var(--gain)" in up and "<polyline" in up and "<path" in up
    assert "var(--loss)" in down
    assert "<polyline" not in ds.sparkline_svg([1])
    assert "<path" not in ds.sparkline_svg([1, 2], area=False)
    assert ds.placeholder_series(7) == ds.placeholder_series(7) and len(ds.placeholder_series(3, 10)) == 10


def test_render_shell_has_header_footer_theme_menu_and_auth_slots():
    page = ds.render_shell(title="테스트", body="<p>본문</p>", active="/harness", canonical_path="/harness", noindex=True, extra_js="console.log(1)")
    assert "<title>테스트</title>" in page and 'name="robots"' in page
    assert 'href="/harness" aria-current="page"' in page and 'href="/"' in page
    assert ds.FONT_STYLESHEET in page and "ta-theme" in page
    assert page.count('role="menuitemradio"') == len(ds.THEMES) + 1
    assert 'data-auth="signed-out"' in page and 'data-plan-badge' in page and "/api/billing/me" in page
    assert 'name="ticker"' in page and 'action="/stocks"' in page
    assert "console.log(1)" in page and 'class="ds ' in page


def test_helpers_format_values():
    assert "+3.80%" in ds.pct(0.038) and 'class="num up"' in ds.pct(0.038)
    assert 'class="num down"' in ds.pct(-0.01) and "–" in ds.pct(None)
    assert ds.money(10062400) == "10,062,400원"
    assert 'class="badge b-teal"' in ds.badge("체결", "b-teal", icon_name="check")
    assert "<svg" in ds.icon("trend", 14) and 'width="14"' in ds.icon("trend", 14)

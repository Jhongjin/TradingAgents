from tradingagents.site.strategy_lenses import build_korean_strategy_lenses


def _chart(points=65, *, trend=500):
    rows = []
    base = 70_000
    for index in range(points):
        close = base + (index * trend)
        rows.append(
            {
                "date": f"2026-03-{(index % 28) + 1:02d}",
                "open": close - 200,
                "high": close + 600,
                "low": close - 800,
                "close": close,
                "volume": 1_000_000 + (index * 10_000),
            }
        )
    return {"status": "available", "points": rows}


def test_korean_strategy_lenses_score_trend_momentum_and_safety():
    lenses = build_korean_strategy_lenses(
        chart=_chart(),
        analysis={"status": "available"},
        analysis_refresh={"recommended": False, "reason": "fresh", "age_days": 0},
        market="KOSPI",
    )

    by_id = {lens["id"]: lens for lens in lenses}

    assert by_id["trend"]["status"] == "positive"
    assert by_id["momentum"]["status"] == "positive"
    assert by_id["analysis_freshness"]["status"] == "positive"
    assert by_id["safety"]["metrics"]["live_trading"] == "disabled"
    assert by_id["forecast"]["status"] in {"positive", "neutral", "caution"}
    assert by_id["forecast"]["metrics"]["backend"] == "naive"
    assert by_id["forecast"]["metrics"]["horizon"] == 20
    assert len(lenses) == 7


def test_korean_strategy_lenses_mark_missing_data_as_unavailable():
    lenses = build_korean_strategy_lenses(
        chart={"status": "unavailable", "points": []},
        analysis={"status": "missing"},
        analysis_refresh={"recommended": True, "reason": "no_completed_public_analysis"},
        market="KOSDAQ",
    )

    by_id = {lens["id"]: lens for lens in lenses}

    assert by_id["trend"]["status"] == "unavailable"
    assert by_id["liquidity"]["status"] == "unavailable"
    assert by_id["analysis_freshness"]["status"] == "caution"

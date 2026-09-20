"""Whether the confirmer's stated confidence means anything.

Measured over the record it has never left 0.78–0.91 — thirteen points of
range across every decision, buys and rejections alike. A confidence that does
not vary cannot be acted on even if it is perfectly informative, because no
threshold separates anything.
"""

from tradingagents.site.rejection_scorecard import MIN_USEFUL_SPREAD, build_confidence_report


def _row(confidence, outcome=None, horizon=20):
    row = {"confirmation_confidence": confidence, "outcomes": []}
    if outcome is not None:
        row["outcomes"] = [{"horizon_days": horizon, "status": "completed", "raw_return": outcome}]
    return row


def test_a_confidence_that_never_moves_is_reported_as_unusable():
    """The real shape: everything between 0.78 and 0.91."""

    rows = [_row(value) for value in (0.78, 0.82, 0.84, 0.88, 0.91)]
    report = build_confidence_report(rows)

    assert report["spread"] < MIN_USEFUL_SPREAD
    assert report["usable"] is False
    assert report["low"] == 0.78 and report["high"] == 0.91


def test_a_confidence_that_uses_its_range_is_usable():
    rows = [_row(value) for value in (0.15, 0.40, 0.62, 0.88)]
    assert build_confidence_report(rows)["usable"] is True


def test_a_missing_confidence_is_not_a_confident_zero():
    """0.00 is the confirmer failing to report one; counting it fakes the spread."""

    rows = [_row(0.0), _row(0.82), _row(0.88)]
    report = build_confidence_report(rows)

    assert report["unreported"] == 1
    assert report["low"] == 0.82           # the zero did not widen the range
    assert report["usable"] is False


def test_a_constant_confidence_correlates_with_nothing_rather_than_zero():
    """Reporting 0.0 would read as measured-and-unrelated, not nothing-to-measure."""

    rows = [_row(0.85, outcome) for outcome in (-0.05, 0.03, -0.02, 0.07, -0.01)]
    assert build_confidence_report(rows)["correlation"] is None


def test_correlation_is_withheld_until_there_are_enough_points():
    rows = [_row(0.2, -0.05), _row(0.9, 0.05)]
    assert build_confidence_report(rows)["correlation"] is None


def test_a_confidence_that_tracks_the_outcome_shows_up():
    rows = [_row(c, r) for c, r in
            ((0.1, -0.08), (0.3, -0.04), (0.5, 0.0), (0.7, 0.04), (0.9, 0.08))]
    assert build_confidence_report(rows)["correlation"] > 0.9


def test_buckets_group_by_tenth_and_count_what_rose():
    rows = [_row(0.82, -0.05), _row(0.84, 0.03), _row(0.91, -0.02)]
    buckets = {row["confidence"]: row for row in build_confidence_report(rows)["buckets"]}

    assert buckets[0.8]["count"] == 2 and buckets[0.8]["rose"] == 1
    assert buckets[0.9]["count"] == 1


def test_an_unscored_horizon_still_counts_toward_the_range():
    """Range collapse is visible before any outcome has elapsed."""

    report = build_confidence_report([_row(0.80), _row(0.90)])
    assert report["count"] == 2 and report["scored"] == 0
    assert report["spread"] == 0.10

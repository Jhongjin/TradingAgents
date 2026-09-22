"""Marking the claims the screen makes when it turns a name down.

A month where the picks lose 3% and the rejections lose 8% says the filter is
discriminating. That survives a drawdown in a way a return figure does not —
and until now only the picks were ever scored.
"""

from tradingagents.site.rejection_scorecard import MIN_EACH_SIDE, build_rejection_scorecard


def _decision(stage, name, value, *, horizon=20, status="completed", reason=None):
    return {
        "stage": stage,
        "ticker_code": name,
        "ticker_name": name,
        "reasons_json": [reason] if reason else [],
        "outcomes": [{"horizon_days": horizon, "status": status, "raw_return": value}],
    }


def _enough(bought_returns, passed_returns, reason="expected return +1.40% below +2.00%"):
    rows = [_decision("ordered", f"b{i}", value) for i, value in enumerate(bought_returns)]
    rows += [_decision("confirmation_rejected", f"p{i}", value, reason=reason)
             for i, value in enumerate(passed_returns)]
    return rows


def test_a_filter_that_told_them_apart_says_so():
    card = build_rejection_scorecard(_enough([-0.03, -0.02, -0.04], [-0.08, -0.09, -0.07]))

    assert card["verdict"] == "filter_discriminated"
    assert card["gap"] > 0
    assert card["bought"]["count"] == 3 and card["passed"]["count"] == 3


def test_a_filter_that_did_not_is_not_dressed_up():
    card = build_rejection_scorecard(_enough([-0.09, -0.08, -0.07], [-0.01, -0.02, 0.03]))

    assert card["verdict"] == "filter_did_not_discriminate"
    assert card["gap"] < 0


def test_too_few_on_either_side_is_refused_rather_than_reported():
    thin = _enough([-0.03], [-0.08, -0.09, -0.07])
    assert build_rejection_scorecard(thin)["verdict"] == "not_enough_data"
    assert build_rejection_scorecard(thin)["gap"] is None
    assert MIN_EACH_SIDE == 3


def test_a_horizon_that_has_not_elapsed_does_not_get_a_vote():
    rows = _enough([-0.03, -0.02, -0.04], [-0.08, -0.09, -0.07])
    rows.append(_decision("ordered", "pending", 0.5, status="pending"))

    card = build_rejection_scorecard(rows)
    assert card["bought"]["count"] == 3
    assert "pending" not in card["bought"]["names"]


def test_the_wrong_horizon_is_not_borrowed_from():
    rows = _enough([-0.03, -0.02, -0.04], [-0.08, -0.09, -0.07])
    card = build_rejection_scorecard(rows, horizon_days=5)
    assert card["verdict"] == "not_enough_data"


def test_the_same_rule_twice_is_one_row_not_two():
    """'+1.40% below +2.00%' and '+1.67% below +2.00%' are one rule."""

    rows = [
        _decision("confirmation_rejected", "a", -0.08, reason="expected return +1.40% below +2.00%"),
        _decision("confirmation_rejected", "b", -0.09, reason="expected return +1.67% below +2.00%"),
        _decision("gate_rejected", "c", -0.02, reason="sector 은행 already holds 2 of 2"),
    ]
    card = build_rejection_scorecard(rows)
    by_reason = {row["reason"]: row for row in card["by_reason"]}

    assert by_reason["기대수익 기준 미달"]["count"] == 2
    assert by_reason["섹터 한도 초과"]["count"] == 1


def test_how_many_of_the_rejections_actually_fell_is_counted():
    card = build_rejection_scorecard(_enough([-0.03, -0.02, -0.04], [-0.08, 0.05, -0.07]))
    assert card["passed"]["fell"] == 2
    assert card["passed"]["count"] == 3


def test_an_exit_is_neither_a_pick_nor_a_rejection():
    rows = _enough([-0.03, -0.02, -0.04], [-0.08, -0.09, -0.07])
    rows.append(_decision("exit", "sold", -0.5))

    card = build_rejection_scorecard(rows)
    assert card["bought"]["count"] == 3 and card["passed"]["count"] == 3


# --------------------------------------------------------------------------
# In public, which is the point
# --------------------------------------------------------------------------

class _Repo:
    """Just enough repository for the page and the endpoint."""

    def __init__(self, rows):
        self.rows = rows
        self.asked = []

    def list_harness_decisions_for_outcomes(self, *, limit=50, stages=("ordered",)):
        self.asked.append(stages)
        return [row for row in self.rows if row["stage"] in stages][:limit]


def test_the_endpoint_asks_for_the_rejections_too():
    """Asking only for 'ordered' is how the comparison stays impossible."""

    from fastapi.testclient import TestClient

    from tradingagents.site.api_app import create_app
    from tradingagents.site.harness_outcome_worker import REJECTED_STAGES

    repo = _Repo(_enough([-0.03, -0.02, -0.04], [-0.08, -0.09, -0.07]))
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))

    body = client.get("/api/harness/scorecard").json()

    assert body["status"] == "available"
    assert body["verdict"] == "filter_discriminated"
    assert set(REJECTED_STAGES) <= set(repo.asked[0])


def test_the_endpoint_says_when_there_is_not_enough_yet():
    from fastapi.testclient import TestClient

    from tradingagents.site.api_app import create_app

    client = TestClient(create_app(repo=_Repo(_enough([-0.03], [-0.08])), load_repo_from_env=False))
    body = client.get("/api/harness/scorecard").json()

    assert body["status"] == "insufficient"
    assert body["verdict"] == "not_enough_data"


def test_a_filter_that_failed_is_said_plainly_on_the_page():
    """The page must not report a working filter more softly than a broken one."""

    from tradingagents.site.harness_pages import _scorecard_card

    html = _scorecard_card(_Repo(_enough([-0.09, -0.08, -0.07], [-0.01, -0.02, 0.03])))

    assert "구분하지 못했습니다" in html
    assert "거르는 기준이 값을 하지 못하고" in html


def test_the_page_still_renders_when_the_scorecard_cannot_be_built():
    from tradingagents.site.harness_pages import _scorecard_card

    class _Broken:
        def list_harness_decisions_for_outcomes(self, **kwargs):
            raise RuntimeError("storage is down")

    assert _scorecard_card(_Broken()) == ""
    assert _scorecard_card(None) == ""

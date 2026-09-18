"""Stored index membership: what counts as usable, and what the screener does with it."""

import json

from tradingagents.dataflows.kr_index_members import (
    INDEX_ETFS,
    MEMBERS_PATH,
    is_tradeable_code,
    index_member_codes,
    load_index_members,
)


def _write(tmp_path, indices):
    path = tmp_path / "members.json"
    path.write_text(json.dumps({"generated_on": "2026-09-18", "indices": indices},
                               ensure_ascii=False), encoding="utf-8")
    return str(path)


def _members(count, *, start=1):
    return [{"code": f"{index:06d}", "name": f"종목{index}"} for index in range(start, start + count)]


def test_the_checked_in_file_has_both_indices_at_a_plausible_size():
    """The file ships with the repo, so a broken one is a broken screener."""

    assert MEMBERS_PATH.exists()
    for index in INDEX_ETFS:
        members = load_index_members(index)
        assert members is not None, index
        assert members.as_of and members.source

    assert len(load_index_members("KOSDAQ150")) == 150
    # KOSPI200 runs a little over 200 between rebalances, when a listed company
    # spins one off and both sit in the index until the next review
    assert 200 <= len(load_index_members("KOSPI200")) <= 210


def test_a_list_that_lost_most_of_its_names_is_refused_rather_than_used(tmp_path):
    """Half a universe would quietly screen half the market, which is worse than failing."""

    path = _write(tmp_path, {"KOSDAQ150": {"as_of": "2026-09-18", "source": "x",
                                           "members": _members(40)}})
    assert load_index_members("KOSDAQ150", path=path) is None
    assert index_member_codes("KOSDAQ150", path=path) == []


def test_a_missing_or_unreadable_file_is_empty_not_an_exception(tmp_path):
    assert load_index_members("KOSDAQ150", path=str(tmp_path / "nope.json")) is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_index_members("KOSDAQ150", path=str(broken)) is None


def test_codes_that_are_not_all_digits_are_still_real_tickers():
    """Newly listed and spun-off shares carry codes like 0126Z0."""

    assert is_tradeable_code("005930")
    assert is_tradeable_code("0126Z0")
    assert not is_tradeable_code("")          # the 현금(원) line every ETF carries
    assert not is_tradeable_code("00593")
    assert not is_tradeable_code("005930A")


def test_the_cash_line_is_not_in_the_shipped_membership():
    for index in INDEX_ETFS:
        for code in load_index_members(index).codes:
            assert is_tradeable_code(code), (index, code)


def test_the_screener_prefers_the_stored_membership_over_the_market_cap_proxy(monkeypatch):
    """This is the point: 36 of 150 KOSDAQ names differed when it was measured."""

    from tradingagents.screener import universe

    monkeypatch.delenv("TRADINGAGENTS_KOSDAQ150_CODES", raising=False)
    codes = universe._kosdaq150_codes_from_pykrx()          # noqa: SLF001
    assert len(codes) == 150
    assert codes == index_member_codes("KOSDAQ150")


def test_an_explicit_list_still_wins_over_the_stored_file(monkeypatch):
    from tradingagents.screener import universe

    monkeypatch.setenv("TRADINGAGENTS_KOSDAQ150_CODES", "005930,000660")
    assert universe._kosdaq150_codes_from_pykrx() == ["005930", "000660"]   # noqa: SLF001


def test_pointing_the_lookup_elsewhere_does_not_leave_a_stale_answer_behind(tmp_path, monkeypatch):
    """The cache is keyed on the resolved path, so the override cannot linger."""

    real = len(load_index_members("KOSDAQ150"))

    monkeypatch.setenv("TRADINGAGENTS_INDEX_MEMBERS_PATH", str(tmp_path / "absent.json"))
    assert load_index_members("KOSDAQ150") is None

    monkeypatch.delenv("TRADINGAGENTS_INDEX_MEMBERS_PATH")
    assert len(load_index_members("KOSDAQ150")) == real

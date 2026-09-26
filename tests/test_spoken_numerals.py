"""Korean has two sets of numbers and the counter picks which one.

"1개만 남았어요" was narrated as "일개만 남았어요". No Korean speaker says that
— it is 한 개 — and it is the first thing a listener notices, because the
number is the point of the sentence.
"""

import pytest

from tradingagents.shorts.voice import native_numeral, spoken_form


@pytest.mark.parametrize("value,expected", [
    (1, "한"), (2, "두"), (3, "세"), (4, "네"), (5, "다섯"),
    (10, "열"), (11, "열한"), (19, "열아홉"),
    (20, "스무"),                      # not 스물, in front of a counter
    (21, "스물한"), (30, "서른"), (99, "아흔아홉"),
])
def test_the_native_numerals(value, expected):
    assert native_numeral(value) == expected


def test_beyond_the_native_range_the_digits_are_left_alone():
    """343종목 is 삼백사십삼 종목, and nobody says 삼백마흔셋."""

    assert native_numeral(100) is None
    assert native_numeral(343) is None
    assert native_numeral(0) is None
    assert spoken_form("343종목에서 1종목이 남았습니다") == "343종목에서 한 종목이 남았습니다"


def test_the_line_that_was_reported():
    assert spoken_form("여기서 1개만 남았어요.") == "여기서 한 개만 남았어요."
    assert spoken_form("여기서 3개만 남았어요.") == "여기서 세 개만 남았어요."


def test_a_space_between_the_number_and_its_counter_is_handled():
    assert spoken_form("정리한 종목 5 개") == "정리한 종목 다섯 개"


@pytest.mark.parametrize("line", [
    "모의 73주 체결",          # 주 is Sino: 칠십삼 주
    "11일 기록",               # 십일 일
    "2026년 9월",              # 이천이십육 년
    "누적 -4.09% · 11일",      # a decimal must not be mistaken for a count
])
def test_sino_korean_counters_are_not_touched(line):
    assert spoken_form(line) == line


def test_a_decimal_is_not_read_as_a_count():
    """"1.5개" is not "한.5개"."""

    assert spoken_form("1.5개") == "1.5개"
    assert spoken_form("12.3건") == "12.3건"


def test_the_acronyms_still_work_and_both_rules_apply_together():
    assert spoken_form("KOSPI200에서 2종목") == "코스피200에서 두 종목"

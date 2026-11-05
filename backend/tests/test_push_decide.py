"""送るかどうかの判定（純関数。plan-device-records §4.1）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tsutae.config import JST
from tsutae.push.decide import decide_send, is_time_to_check

DAY1 = date(2026, 11, 1)
CYCLE = 14
TODAY = date(2026, 11, 9)


def _at(hh: int, mm: int, ss: int = 0, day: date = TODAY) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=JST)


def _decide(at: datetime | None = None, **overrides: object) -> str:
    args: dict[str, object] = {
        "notify_time": "20:00",
        "last_sent_date": None,
        "marked_today": False,
        "last_day1": DAY1,
        "cycle_days": CYCLE,
    }
    return decide_send(at or _at(20, 0), **{**args, **overrides})


def test_due_at_the_time() -> None:
    assert _decide() == "due"


def test_marked_today_is_not_sent() -> None:
    assert _decide(marked_today=True) == "marked"


def test_no_course_is_not_sent() -> None:
    assert _decide(last_day1=None, cycle_days=None) == "no_course"


def test_sent_today_is_not_sent_again() -> None:
    assert _decide(last_sent_date=TODAY) == "sent_today"


def test_sent_yesterday_is_due() -> None:
    assert _decide(last_sent_date=TODAY - timedelta(days=1)) == "due"


@pytest.mark.parametrize(
    "at, expected",
    [
        (_at(19, 59, 59), "before_time"),
        (_at(20, 0, 0), "due"),
        (_at(20, 9, 59), "due"),
        (_at(20, 10, 0), "due"),
        (_at(20, 10, 1), "window_passed"),
        (_at(23, 0, 0), "window_passed"),
        (_at(7, 0, 0), "before_time"),
    ],
)
def test_time_window(at: datetime, expected: str) -> None:
    assert _decide(at) == expected


def test_latest_time_of_the_day_stays_in_the_day() -> None:
    assert _decide(_at(23, 40), notify_time="23:30") == "due"
    assert _decide(_at(23, 41), notify_time="23:30") == "window_passed"
    # 次の日の 0 時台は別の日の「時刻の前」で、前の日の続きにならない
    next_day = TODAY + timedelta(days=1)
    assert _decide(_at(0, 5, day=next_day), notify_time="23:30") == "before_time"


def test_earliest_time_of_the_day() -> None:
    assert _decide(_at(0, 0), notify_time="00:00") == "due"


@pytest.mark.parametrize(
    "day, expected",
    [
        # Day1 + 14 日 + 14 日 = 11/29 までが送る期間
        (date(2026, 11, 29), "due"),
        (date(2026, 11, 30), "period_over"),
    ],
)
def test_period_boundary(day: date, expected: str) -> None:
    assert _decide(_at(20, 0, day=day)) == expected


def test_cycle_days_changes_the_period() -> None:
    day = date(2026, 12, 6)  # 11/1 + 21 + 14 = 12/6
    assert _decide(_at(20, 0, day=day), cycle_days=21) == "due"
    assert _decide(_at(20, 0, day=day), cycle_days=14) == "period_over"


def test_future_course_counts_as_the_last_course() -> None:
    """次のコースを先に入れた間も、最後のコースの期間の内なので送る。"""
    assert _decide(last_day1=TODAY + timedelta(days=3)) == "due"


def test_missing_cycle_days_with_a_course_is_refused() -> None:
    with pytest.raises(ValueError):
        _decide(cycle_days=None)


@pytest.mark.parametrize("bad", ["", "8:00", "24:00", "20:61", "20:00:00", "abc"])
def test_bad_notify_time_is_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        _decide(notify_time=bad)


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError):
        _decide(datetime(2026, 11, 9, 20, 0, 0))


def test_other_timezone_is_read_as_jst() -> None:
    assert _decide(_at(20, 0).astimezone(UTC)) == "due"


def test_is_time_to_check_is_the_cheap_part_of_the_decision() -> None:
    """Skill を読む前の絞り込み。印・コースを見ない。"""
    assert is_time_to_check(_at(20, 5), "20:00", None) is True
    assert is_time_to_check(_at(19, 59), "20:00", None) is False
    assert is_time_to_check(_at(20, 11), "20:00", None) is False
    assert is_time_to_check(_at(20, 5), "20:00", TODAY) is False

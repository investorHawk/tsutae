"""tsutae.course（コースと Day の純関数）のテスト。

症例は全て合成。日付はデモ患者（docs/architecture.md §6）に合わせる:
C1 実投与 2026-09-27 ／ C2 予定 10-11・実投与 10-13（延期2日）／ C3 実投与 10-27。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tsutae.course import (
    CourseValidationError,
    build_schedule,
    course_for_date,
    current_course,
    day_of,
    delay_note,
    grid_days,
    previous_course,
    validate_courses,
)
from tsutae.schemas import Course, CourseSchedule

PID = "P-TEST0001"
C1_DAY1 = date(2026, 9, 27)
C2_PLANNED = date(2026, 10, 11)
C2_DAY1 = date(2026, 10, 13)
C3_DAY1 = date(2026, 10, 27)
DEMO_VISIT = date(2026, 11, 9)


def _course(no: int, infusion: date, planned: date | None = None) -> Course:
    return Course(
        patient_id=PID, course_no=no, infusion_date=infusion, planned_date=planned
    )


def _demo_courses() -> list[Course]:
    return [
        _course(1, C1_DAY1),
        _course(2, C2_DAY1, planned=C2_PLANNED),
        _course(3, C3_DAY1),
    ]


def _folfox(courses: list[Course], no: int) -> CourseSchedule:
    return build_schedule(courses, no, cycle_days=14, pump_removal_day=3)


# ---------------------------------------------------------------------------
# 14日標準
# ---------------------------------------------------------------------------


def test_standard_14_day_course_without_next() -> None:
    courses = [_course(1, C1_DAY1)]
    s = _folfox(courses, 1)
    assert s == CourseSchedule(
        course_no=1,
        infusion_date=C1_DAY1,
        day1_date=C1_DAY1,
        last_day_date=date(2026, 10, 10),
        pump_removal_date=date(2026, 9, 29),
        previous_infusion_date=None,
        delay_days=None,
    )
    assert day_of(C1_DAY1, s, courses=courses) == 1
    assert day_of(date(2026, 9, 29), s, courses=courses) == 3
    assert day_of(date(2026, 10, 10), s, courses=courses) == 14
    assert grid_days(s) == list(range(1, 15))
    assert delay_note(s) is None


def test_on_time_next_course_ends_previous_at_day14() -> None:
    courses = [_course(1, C1_DAY1), _course(2, C1_DAY1 + timedelta(days=14))]
    s1 = _folfox(courses, 1)
    assert s1.last_day_date == date(2026, 10, 10)
    assert grid_days(s1) == list(range(1, 15))
    assert day_of(date(2026, 10, 10), s1, courses=courses) == 14
    assert day_of(date(2026, 10, 11), s1, courses=courses) is None


def test_demo_c3_visit_is_day14() -> None:
    courses = _demo_courses()
    s3 = _folfox(courses, 3)
    assert s3.day1_date == C3_DAY1
    assert s3.last_day_date == DEMO_VISIT
    assert s3.previous_infusion_date == C2_DAY1
    assert s3.pump_removal_date == date(2026, 10, 29)
    assert day_of(DEMO_VISIT, s3, courses=courses) == 14
    assert grid_days(s3, until=DEMO_VISIT) == list(range(1, 15))
    assert current_course(courses, DEMO_VISIT) == courses[2]


# ---------------------------------------------------------------------------
# 延期（前コースが16日になる）
# ---------------------------------------------------------------------------


def test_delay_makes_previous_course_16_days() -> None:
    courses = _demo_courses()
    s1 = _folfox(courses, 1)
    assert s1.last_day_date == date(2026, 10, 12)
    assert grid_days(s1) == list(range(1, 17))
    assert day_of(date(2026, 10, 12), s1, courses=courses) == 16
    assert day_of(C2_DAY1, s1, courses=courses) is None
    assert day_of(DEMO_VISIT, s1, courses=courses) is None
    assert s1.delay_days is None
    assert delay_note(s1) is None


def test_delayed_course_counts_from_actual_infusion() -> None:
    courses = _demo_courses()
    s2 = _folfox(courses, 2)
    assert s2.day1_date == C2_DAY1
    assert s2.infusion_date == C2_DAY1
    assert s2.last_day_date == date(2026, 10, 26)
    assert s2.pump_removal_date == date(2026, 10, 15)
    assert s2.previous_infusion_date == C1_DAY1
    assert s2.delay_days == 2
    assert delay_note(s2) == "延期（予定より2日）"
    # 予定日（10/11）は実投与前なので C2 の Day ではない
    assert day_of(C2_PLANNED, s2, courses=courses) is None
    assert day_of(C2_DAY1, s2, courses=courses) == 1
    assert course_for_date(courses, C2_PLANNED) == courses[0]


def test_delay_note_ignores_zero_none_and_early() -> None:
    on_time = _folfox([_course(1, C1_DAY1, planned=C1_DAY1)], 1)
    assert on_time.delay_days == 0
    assert delay_note(on_time) is None
    early = _folfox([_course(1, C1_DAY1, planned=C1_DAY1 + timedelta(days=1))], 1)
    assert early.delay_days == -1
    assert delay_note(early) is None
    long_delay = _folfox([_course(1, C1_DAY1, planned=C1_DAY1 - timedelta(7))], 1)
    assert delay_note(long_delay) == "延期（予定より7日）"


# ---------------------------------------------------------------------------
# 次コース未登録で Day15 以降
# ---------------------------------------------------------------------------


def test_unregistered_next_course_counts_day15_and_later() -> None:
    courses = _demo_courses()
    s3 = _folfox(courses, 3)
    assert s3.last_day_date == DEMO_VISIT  # cycle_days から
    day15 = DEMO_VISIT + timedelta(days=1)
    day17 = DEMO_VISIT + timedelta(days=3)
    assert day_of(day15, s3, courses=courses) == 15
    assert day_of(day17, s3, courses=courses) == 17
    assert course_for_date(courses, day17) == courses[2]
    assert current_course(courses, day17) == courses[2]


def test_grid_days_extends_to_until() -> None:
    s3 = _folfox(_demo_courses(), 3)
    day17 = DEMO_VISIT + timedelta(days=3)
    assert grid_days(s3, until=day17) == list(range(1, 18))
    assert grid_days(s3, until=date(2026, 11, 2)) == list(range(1, 15))
    assert grid_days(s3) == list(range(1, 15))


def test_registered_next_course_stops_counting() -> None:
    courses = [*_demo_courses(), _course(4, date(2026, 11, 10))]
    s3 = _folfox(courses, 3)
    assert s3.last_day_date == DEMO_VISIT
    assert day_of(date(2026, 11, 10), s3, courses=courses) is None
    assert day_of(date(2026, 11, 20), s3, courses=courses) is None


def test_day_of_requires_courses() -> None:
    # 2引数では「次コースが登録済み」と「未登録」を区別できず、誤った Day を返しうる。
    # 黙って数え続けないよう、courses なしでは呼べない
    courses = [*_demo_courses(), _course(4, date(2026, 11, 10))]
    s3 = _folfox(courses, 3)
    with pytest.raises(TypeError):
        day_of(date(2026, 11, 10), s3)  # type: ignore[call-arg]


def test_previous_schedule_is_none_from_next_course_start() -> None:
    # 前コースの日程に今コースの記録を当てても Day を数え続けない（§3）
    courses = _demo_courses()
    s1 = _folfox(courses, 1)
    s2 = _folfox(courses, 2)
    assert day_of(C2_DAY1, s1, courses=courses) is None
    assert day_of(DEMO_VISIT, s1, courses=courses) is None
    assert day_of(C3_DAY1 - timedelta(days=1), s2, courses=courses) == 14
    assert day_of(C3_DAY1, s2, courses=courses) is None
    assert day_of(date(2026, 10, 29), s2, courses=courses) is None


def test_day_of_rejects_courses_without_schedule_course() -> None:
    s1 = _folfox(_demo_courses(), 1)
    for d in (C1_DAY1 - timedelta(days=1), date(2026, 11, 20)):
        with pytest.raises(CourseValidationError) as exc:
            day_of(d, s1, courses=[])
        assert exc.value.code == "course_not_found"


def test_day_of_rejects_courses_with_other_day1() -> None:
    s1 = _folfox(_demo_courses(), 1)
    other = [_course(1, date(2026, 1, 1)), _course(2, date(2026, 1, 15))]
    for d in (C1_DAY1 - timedelta(days=1), C2_DAY1):
        with pytest.raises(CourseValidationError) as exc:
            day_of(d, s1, courses=other)
        assert exc.value.code == "schedule_mismatch"


# ---------------------------------------------------------------------------
# Day1 前・同日
# ---------------------------------------------------------------------------


def test_before_day1_is_none() -> None:
    courses = _demo_courses()
    s3 = _folfox(courses, 3)
    assert day_of(C3_DAY1 - timedelta(days=1), s3, courses=courses) is None
    assert grid_days(s3, until=C3_DAY1 - timedelta(days=5)) == list(range(1, 15))
    before_c1 = C1_DAY1 - timedelta(days=1)
    assert course_for_date(courses, before_c1) is None
    assert current_course(courses, before_c1) is None


def test_same_day_as_infusion_is_day1_of_that_course() -> None:
    courses = _demo_courses()
    s2 = _folfox(courses, 2)
    assert day_of(C2_DAY1, s2, courses=courses) == 1
    assert course_for_date(courses, C2_DAY1) == courses[1]
    assert current_course(courses, C2_DAY1) == courses[1]
    assert course_for_date(courses, C2_DAY1 - timedelta(days=1)) == courses[0]


def test_grid_days_until_same_day_as_day1() -> None:
    s = _folfox([_course(1, C1_DAY1)], 1)
    assert grid_days(s, until=C1_DAY1) == list(range(1, 15))


def test_grid_days_with_next_course_registered_early() -> None:
    # 現状の挙動: 今コースの列は Day1〜max(last_day_date の Day, until の Day)。
    # CourseSchedule に cycle_days が無いので、§3 の「max(cycle_days, until)」（14列）
    # にはならない（11列）。§3 の決定待ち
    courses = [*_demo_courses(), _course(4, date(2026, 11, 7))]
    s3 = _folfox(courses, 3)
    assert s3.last_day_date == date(2026, 11, 6)
    assert grid_days(s3, until=date(2026, 11, 5)) == list(range(1, 12))
    assert grid_days(s3) == list(range(1, 12))


def test_course_ending_on_day12_has_12_columns() -> None:
    courses = [_course(1, C1_DAY1), _course(2, C1_DAY1 + timedelta(days=12))]
    s1 = _folfox(courses, 1)
    assert s1.last_day_date == C1_DAY1 + timedelta(days=11)
    assert grid_days(s1) == list(range(1, 13))
    assert day_of(C1_DAY1 + timedelta(days=11), s1, courses=courses) == 12
    assert day_of(C1_DAY1 + timedelta(days=12), s1, courses=courses) is None


# ---------------------------------------------------------------------------
# CAPOX 21日・pump_removal_day=None
# ---------------------------------------------------------------------------


def test_capox_21_day_course() -> None:
    day1 = date(2026, 10, 1)
    courses = [_course(1, day1)]
    s = build_schedule(courses, 1, cycle_days=21, pump_removal_day=None)
    assert s.last_day_date == date(2026, 10, 21)
    assert s.pump_removal_date is None
    assert grid_days(s) == list(range(1, 22))
    assert day_of(date(2026, 10, 21), s, courses=courses) == 21
    assert day_of(date(2026, 10, 22), s, courses=courses) == 22  # 次コース未登録


def test_capox_second_course_on_time() -> None:
    courses = [_course(1, date(2026, 10, 1)), _course(2, date(2026, 10, 22))]
    s1 = build_schedule(courses, 1, cycle_days=21, pump_removal_day=None)
    s2 = build_schedule(courses, 2, cycle_days=21, pump_removal_day=None)
    assert s1.last_day_date == date(2026, 10, 21)
    assert grid_days(s1) == list(range(1, 22))
    assert day_of(date(2026, 10, 22), s1, courses=courses) is None
    assert s2.previous_infusion_date == date(2026, 10, 1)
    assert s2.last_day_date == date(2026, 11, 11)


def test_pump_removal_day_none_with_14_day_cycle() -> None:
    s = build_schedule([_course(1, C1_DAY1)], 1, cycle_days=14, pump_removal_day=None)
    assert s.pump_removal_date is None
    assert s.last_day_date == date(2026, 10, 10)


# ---------------------------------------------------------------------------
# 前コース
# ---------------------------------------------------------------------------


def test_previous_course() -> None:
    courses = _demo_courses()
    assert previous_course(courses, 3) == courses[1]
    assert previous_course(courses, 2) == courses[0]


def test_no_previous_course() -> None:
    courses = _demo_courses()
    assert previous_course(courses, 1) is None
    assert previous_course([], 1) is None
    assert _folfox(courses, 1).previous_infusion_date is None


def test_previous_course_skips_missing_number() -> None:
    courses = [_course(1, C1_DAY1), _course(3, C3_DAY1)]
    assert previous_course(courses, 3) == courses[0]
    assert _folfox(courses, 3).previous_infusion_date == C1_DAY1
    assert _folfox(courses, 1).last_day_date == C3_DAY1 - timedelta(days=1)


# ---------------------------------------------------------------------------
# 順不同・引数を書き換えない
# ---------------------------------------------------------------------------


def test_unordered_courses_give_same_results() -> None:
    ordered = _demo_courses()
    shuffled = [ordered[2], ordered[0], ordered[1]]
    snapshot = list(shuffled)
    for no in (1, 2, 3):
        assert _folfox(shuffled, no) == _folfox(ordered, no)
    assert course_for_date(shuffled, date(2026, 10, 20)) == ordered[1]
    assert current_course(shuffled, DEMO_VISIT) == ordered[2]
    assert previous_course(shuffled, 3) == ordered[1]
    s1 = _folfox(ordered, 1)
    assert day_of(C2_DAY1, s1, courses=shuffled) is None
    assert shuffled == snapshot


def test_accepts_tuple() -> None:
    courses = tuple(_demo_courses())
    s = _folfox(list(courses), 2)
    assert build_schedule(courses, 2, 14, 3) == s
    assert course_for_date(courses, C3_DAY1) == courses[2]
    assert day_of(C2_DAY1, s, courses=courses) == 1
    assert validate_courses(courses) == list(courses)


def test_does_not_mutate_list_argument() -> None:
    ordered = _demo_courses()
    courses = [ordered[2], ordered[0], ordered[1]]
    snapshot = list(courses)
    s1 = build_schedule(courses, 1, 14, 3)
    validate_courses(courses)
    course_for_date(courses, C3_DAY1)
    current_course(courses, DEMO_VISIT)
    previous_course(courses, 3)
    day_of(C2_DAY1, s1, courses=courses)
    assert courses == snapshot
    assert all(a is b for a, b in zip(courses, snapshot, strict=True))


def test_empty_courses() -> None:
    assert course_for_date([], DEMO_VISIT) is None
    assert current_course([], DEMO_VISIT) is None
    with pytest.raises(ValueError):
        build_schedule([], 1, 14, 3)


# ---------------------------------------------------------------------------
# 入力の検証
# ---------------------------------------------------------------------------


def test_unknown_course_no_raises() -> None:
    with pytest.raises(ValueError, match="course_no"):
        _folfox(_demo_courses(), 4)


def test_duplicate_course_no_raises() -> None:
    courses = [_course(1, C1_DAY1), _course(1, C2_DAY1)]
    with pytest.raises(ValueError, match="重複"):
        _folfox(courses, 1)
    with pytest.raises(ValueError):
        course_for_date(courses, C2_DAY1)


def test_infusion_dates_must_increase_with_course_no() -> None:
    same_day = [_course(1, C1_DAY1), _course(2, C1_DAY1)]
    reversed_dates = [_course(1, C2_DAY1), _course(2, C1_DAY1)]
    for courses in (same_day, reversed_dates):
        with pytest.raises(ValueError, match="実投与日"):
            _folfox(courses, 1)
        with pytest.raises(ValueError):
            current_course(courses, DEMO_VISIT)
        with pytest.raises(ValueError):
            previous_course(courses, 2)


def test_mixed_patients_raise() -> None:
    other = Course(patient_id="P-TEST0002", course_no=2, infusion_date=C2_DAY1)
    with pytest.raises(ValueError, match="患者"):
        _folfox([_course(1, C1_DAY1), other], 1)


@pytest.mark.parametrize("cycle_days", [0, -1])
def test_invalid_cycle_days_raise(cycle_days: int) -> None:
    with pytest.raises(ValueError, match="cycle_days"):
        build_schedule([_course(1, C1_DAY1)], 1, cycle_days, 3)


@pytest.mark.parametrize("pump", [0, -2])
def test_invalid_pump_removal_day_raise(pump: int) -> None:
    with pytest.raises(ValueError, match="pump_removal_day"):
        build_schedule([_course(1, C1_DAY1)], 1, 14, pump)


def test_last_course_keeps_counting_with_courses() -> None:
    # courses に今コースの次が無い（最後のコース）なら数え続ける
    courses = _demo_courses()
    s3 = _folfox(courses, 3)
    assert day_of(DEMO_VISIT + timedelta(days=10), s3, courses=courses) == 24


# ---------------------------------------------------------------------------
# validate_courses（D2 の保存前の検査にも使う）
# ---------------------------------------------------------------------------


def test_validate_courses_returns_sorted_new_list() -> None:
    ordered = _demo_courses()
    shuffled = [ordered[2], ordered[0], ordered[1]]
    snapshot = list(shuffled)
    result = validate_courses(shuffled)
    assert result == ordered
    assert result is not shuffled
    assert shuffled == snapshot
    assert validate_courses([]) == []


@pytest.mark.parametrize(
    ("courses", "code"),
    [
        ([_course(1, C1_DAY1), _course(1, C2_DAY1)], "course_duplicate"),
        ([_course(1, C1_DAY1), _course(2, C1_DAY1)], "course_order"),
        ([_course(1, C2_DAY1), _course(2, C1_DAY1)], "course_order"),
        (
            [
                _course(1, C1_DAY1),
                Course(patient_id="P-TEST0002", course_no=2, infusion_date=C2_DAY1),
            ],
            "course_patient_mismatch",
        ),
    ],
)
def test_validate_courses_rejects_contradictions(
    courses: list[Course], code: str
) -> None:
    with pytest.raises(CourseValidationError) as exc:
        validate_courses(courses)
    assert exc.value.code == code
    assert isinstance(exc.value, ValueError)


def test_validate_courses_before_upsert_catches_mistyped_date() -> None:
    # D2 で C2 の実投与日を C1 より前に打ち間違えた: 保存前に既存と合わせて検査する
    existing = _demo_courses()
    new = _course(2, date(2026, 9, 20))
    merged = [c for c in existing if c.course_no != new.course_no] + [new]
    with pytest.raises(CourseValidationError) as exc:
        validate_courses(merged)
    assert exc.value.code == "course_order"

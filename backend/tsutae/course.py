"""コースと Day の計算（純関数。DB に触れない）。

- Day1 = 実投与日。次コースの実投与日の前日までが今コース
- 次コースが未登録なら `infusion_date + cycle_days - 1` を最終日とする。それ以降の
  記録は、次コースが登録されるまで今コースの Day15, 16… として数える
- `day_of` は courses（キーワード専用・必須）で次コースの有無を確かめる。次コースの
  実投与日以降は None（CourseSchedule だけでは「次コース登録済み」と「未登録」を
  区別できないため、courses なしでは呼べない）
- 延期は `planned_date` との差で表す。延期の理由は扱わない（推測しない）
- 引数は書き換えない。courses は順不同でよい（中で course_no 順に並べ直す）
- courses に矛盾があれば、どの関数も `CourseValidationError`（ValueError）。`code` は
  API に載せる短い文字列。D2 の保存前の検査には `validate_courses` を使う

契約は docs/architecture.md §3。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from itertools import pairwise

from tsutae.schemas import Course, CourseSchedule

__all__ = [
    "CourseValidationError",
    "build_schedule",
    "course_for_date",
    "current_course",
    "day_of",
    "delay_note",
    "grid_days",
    "previous_course",
    "validate_courses",
]


class CourseValidationError(ValueError):
    """courses や日程に矛盾がある。`code` は DB・API に載せる短い文字列。

    - course_duplicate: course_no が重複
    - course_order: 実投与日が course_no の順に厳密に増えていない（同日・逆順）
    - course_patient_mismatch: 別の患者のコースが混ざっている
    - course_not_found: 指定の course_no のコースが無い
    - schedule_mismatch: 日程（CourseSchedule）と courses が合わない
    """

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


def validate_courses(courses: Sequence[Course]) -> list[Course]:
    """course_no 順に並べた新しいリストを返す。矛盾があれば CourseValidationError。

    - course_no の重複は不可
    - 実投与日は course_no とともに厳密に増えること（同日・逆順は不可）
    - 全て同じ患者のコースであること

    D2 の保存前の検査（upsert は同じ course_no を置き換える）::

        validate_courses([c for c in existing if c.course_no != new.course_no] + [new])
    """
    ordered = sorted(courses, key=lambda c: c.course_no)
    if len({c.patient_id for c in ordered}) > 1:
        raise CourseValidationError(
            "course_patient_mismatch", "courses に別の患者のコースが混ざっている"
        )
    for prev, cur in pairwise(ordered):
        if prev.course_no == cur.course_no:
            raise CourseValidationError(
                "course_duplicate", f"course_no {cur.course_no} が重複している"
            )
        if cur.infusion_date <= prev.infusion_date:
            raise CourseValidationError(
                "course_order",
                f"実投与日が course_no の順に増えていない"
                f"（第{prev.course_no}コース {prev.infusion_date} → "
                f"第{cur.course_no}コース {cur.infusion_date}）",
            )
    return ordered


def _find(ordered: list[Course], course_no: int) -> Course:
    for course in ordered:
        if course.course_no == course_no:
            return course
    raise CourseValidationError(
        "course_not_found", f"course_no {course_no} のコースが登録されていない"
    )


def _next_of(ordered: list[Course], course_no: int) -> Course | None:
    return next((c for c in ordered if c.course_no > course_no), None)


def _prev_of(ordered: list[Course], course_no: int) -> Course | None:
    earlier = [c for c in ordered if c.course_no < course_no]
    return earlier[-1] if earlier else None


def _day_number(d: date, day1: date) -> int:
    return (d - day1).days + 1


def build_schedule(
    courses: Sequence[Course],
    course_no: int,
    cycle_days: int,
    pump_removal_day: int | None,
) -> CourseSchedule:
    """course_no のコース日程を組み立てる。

    - last_day_date: 次コースの実投与日の前日。未登録なら infusion_date + cycle_days - 1
    - pump_removal_date: Day(pump_removal_day)。None なら None（CAPOX）
    - delay_days: (infusion_date - planned_date).days。planned_date が無ければ None
    """
    if cycle_days < 1:
        raise ValueError(f"cycle_days は 1 以上（{cycle_days}）")
    if pump_removal_day is not None and pump_removal_day < 1:
        raise ValueError(f"pump_removal_day は 1 以上（{pump_removal_day}）")
    ordered = validate_courses(courses)
    course = _find(ordered, course_no)
    day1 = course.infusion_date
    nxt = _next_of(ordered, course_no)
    prev = _prev_of(ordered, course_no)
    if nxt is not None:
        last_day = nxt.infusion_date - timedelta(days=1)
    else:
        last_day = day1 + timedelta(days=cycle_days - 1)
    pump = (
        day1 + timedelta(days=pump_removal_day - 1)
        if pump_removal_day is not None
        else None
    )
    delay = (
        (day1 - course.planned_date).days if course.planned_date is not None else None
    )
    return CourseSchedule(
        course_no=course.course_no,
        infusion_date=course.infusion_date,
        day1_date=day1,
        last_day_date=last_day,
        pump_removal_date=pump,
        previous_infusion_date=prev.infusion_date if prev is not None else None,
        delay_days=delay,
    )


def day_of(
    d: date,
    schedule: CourseSchedule,
    *,
    courses: Sequence[Course],
) -> int | None:
    """d がそのコースの何日目か（Day1 = 実投与日）。

    - Day1 より前は None
    - 次コース（schedule.course_no より大きい最小の course_no）の実投与日以降は None
    - 次コースが未登録なら last_day_date を過ぎても数え続ける（Day15, 16…）
    - courses は schedule を組み立てたのと同じもの。schedule のコースが無い、または
      その実投与日が schedule.day1_date と違えば CourseValidationError（日付に
      かかわらず先に検査する）
    """
    ordered = validate_courses(courses)
    course = _find(ordered, schedule.course_no)
    if course.infusion_date != schedule.day1_date:
        raise CourseValidationError(
            "schedule_mismatch",
            f"第{schedule.course_no}コースの実投与日 {course.infusion_date} が"
            f"日程の Day1 {schedule.day1_date} と違う",
        )
    if d < schedule.day1_date:
        return None
    nxt = _next_of(ordered, schedule.course_no)
    if nxt is not None and d >= nxt.infusion_date:
        return None
    return _day_number(d, schedule.day1_date)


def grid_days(schedule: CourseSchedule, until: date | None = None) -> list[int]:
    """経過表の列にする Day の一覧。

    - until なし（前コース）: Day1〜last_day_date の Day
    - until あり（今コース）: Day1〜max(last_day_date の Day, until の Day)。
      次コース未登録なら last_day_date の Day は cycle_days と一致する
    - 次コースが cycle_days より早く登録されていれば、その前日の Day までになる
      （§3 の「max(cycle_days, until)」とは違う。CourseSchedule に cycle_days が無い）
    """
    last = _day_number(schedule.last_day_date, schedule.day1_date)
    if until is not None:
        last = max(last, _day_number(until, schedule.day1_date))
    return list(range(1, last + 1))


def delay_note(schedule: CourseSchedule) -> str | None:
    """予定より遅れて投与したときの注記（例「延期（予定より2日）」）。理由は書かない。"""
    if schedule.delay_days is None or schedule.delay_days <= 0:
        return None
    return f"延期（予定より{schedule.delay_days}日）"


def course_for_date(courses: Sequence[Course], d: date) -> Course | None:
    """d が属するコース（実投与日が d 以前で最大の course_no）。最初の投与前は None。

    最後のコースは次コースが登録されるまで続く（cycle_days を過ぎても同じコース）。
    """
    started = [c for c in validate_courses(courses) if c.infusion_date <= d]
    return started[-1] if started else None


def current_course(courses: Sequence[Course], today: date) -> Course | None:
    """今日のコース（実投与日が today 以前で最大の course_no）。"""
    return course_for_date(courses, today)


def previous_course(courses: Sequence[Course], course_no: int) -> Course | None:
    """course_no の直前に登録されたコース（course_no より小さい最大のもの）。"""
    return _prev_of(validate_courses(courses), course_no)

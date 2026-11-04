"""医師 API の患者まわりの応答の形（D1 の一覧の追加項目・D2 の患者の受診と記録）。

- 患者一覧: last_record_date（最後の記録日）・current_course_no（今日のコース。
  `course.current_course` に `config.today()`）・next_visit（今のコースの次回受診予定日。今日より前なら null）。
  無ければ null。コースに矛盾があっても一覧は止めない（その患者は null）
- 患者の受診: 印刷済み・期限切れも含めて新しい順。受付番号は消えていれば null。
  report_available はレポートを開ける（受付番号が残っている ready）か
- 患者の記録: 直近 `RECENT_ENTRIES_MAX` 件を新しい順。クローズ回答はコード
  （question_key・value・temperature）のまま返し、表示名は画面で引く。自由記載は有無
  （has_free_text）だけで原文は返さない（原文は D6 の未処理の記載だけに出す）
- 医師画面の UX の見直し（2026-11-04 夜）: 一覧の current_day（今日の Day）・
  days_since_last_record・record_stale（最後の記録が今日から `STALE_AFTER_DAYS` 日以上前、
  または記録なし）、記録の course_no・day（記録日のコースと Day）、未処理・変換ログの
  visit（受診の見出し）。Day は `course.course_for_date` の Day1 = 実投与日から数える
  （次のコースが未登録なら cycle_days を過ぎても数え続ける。`course.day_of` と同じ）
- 純関数（DB に触れない）。引数は書き換えない
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from tsutae.course import CourseValidationError, course_for_date, current_course
from tsutae.schemas import Course, Entry

__all__ = [
    "RECENT_ENTRIES_MAX",
    "STALE_AFTER_DAYS",
    "CourseDay",
    "course_day",
    "course_summary",
    "day_fields",
    "entry_summary",
    "patient_visit",
    "record_gap",
    "visit_header",
]

RECENT_ENTRIES_MAX = 30
# 最後の記録が今日から何日以上前なら「記録が途切れた」とするか（今日を含めない）
STALE_AFTER_DAYS = 3

CourseDay = tuple[int, int]


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def course_day(courses: Sequence[Course], d: date) -> CourseDay | None:
    """d の (course_no, Day)。最初の投与の前・コースに矛盾があれば None。"""
    try:
        course = course_for_date(courses, d)
    except CourseValidationError:
        return None
    if course is None:
        return None
    return course.course_no, (d - course.infusion_date).days + 1


def course_summary(courses: Sequence[Course], today: date) -> dict[str, Any]:
    """{current_course_no, current_day, next_visit}。今コースが無ければ null。

    next_visit は今日以降の予定日だけを出す（過去の予定日は null。画面は「—」）。
    """
    try:
        current = current_course(courses, today)
    except CourseValidationError:
        current = None
    if current is None:
        return {"current_course_no": None, "current_day": None, "next_visit": None}
    upcoming = current.next_visit
    if upcoming is not None and upcoming < today:
        upcoming = None
    return {
        "current_course_no": current.course_no,
        "current_day": (today - current.infusion_date).days + 1,
        "next_visit": _iso(upcoming),
    }


def record_gap(last: date | None, today: date) -> dict[str, Any]:
    """{days_since_last_record, record_stale}。記録が無ければ日数は null で途切れ扱い。"""
    if last is None:
        return {"days_since_last_record": None, "record_stale": True}
    days = (today - last).days
    return {"days_since_last_record": days, "record_stale": days >= STALE_AFTER_DAYS}


def patient_visit(visit: dict[str, Any], unprocessed_count: int) -> dict[str, Any]:
    """患者の画面の受診1件。受付番号が消えた受診（印刷済み・期限切れ）は開けない。"""
    is_open = visit["reception_no"] is not None
    return {
        "id": visit["id"],
        "reception_no": visit["reception_no"],
        "visit_date": visit["visit_date"].isoformat(),
        "created_at": visit["created_at"].isoformat(),
        "status": visit["status"],
        "fallback": visit["fallback"],
        "report_available": is_open and visit["status"] == "ready",
        "unprocessed_count": unprocessed_count if is_open else 0,
    }


def visit_header(visit: dict[str, Any], at: datetime) -> dict[str, Any]:
    """未処理・変換ログの見出しの受診1件。受付番号は印刷済み・期限切れで null。

    report_available はレポートを開ける（受付番号が残っていて期限内の ready）か。
    """
    is_open = visit["reception_no"] is not None and visit["expires_at"] > at
    return {
        "id": visit["id"],
        "reception_no": visit["reception_no"],
        "patient_id": visit["patient_id"],
        "visit_date": visit["visit_date"].isoformat(),
        "created_at": visit["created_at"].isoformat(),
        "status": visit["status"],
        "fallback": visit["fallback"],
        "report_available": is_open and visit["status"] == "ready",
    }


def _day_fields(day: CourseDay | None) -> dict[str, int | None]:
    if day is None:
        return {"course_no": None, "day": None}
    return {"course_no": day[0], "day": day[1]}


def entry_summary(entry: Entry, courses: Sequence[Course]) -> dict[str, Any]:
    """患者の画面の記録1件（記録日のコースと Day つき）。自由記載の原文は入れない。"""
    return {
        "id": entry.id,
        "recorded_at": entry.recorded_at.isoformat(),
        "record_date": entry.record_date.isoformat(),
        **day_fields(courses, entry.record_date),
        "kind": entry.kind,
        "by_proxy": entry.by_proxy,
        "answers": [
            {
                "question_key": a.question_key,
                "value": a.value,
                "temperature": a.temperature,
            }
            for a in entry.answers
        ],
        "has_free_text": bool(entry.free_text and entry.free_text.strip()),
    }


def day_fields(courses: Sequence[Course], d: date) -> dict[str, int | None]:
    """{course_no, day}（d のコースと Day。コース外・矛盾は null）。"""
    return _day_fields(course_day(courses, d))

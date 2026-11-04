"""医師 API の患者まわりの応答の形（D1 の一覧の追加項目・D2 の患者の受診と記録）。

- 患者一覧: last_record_date（最後の記録日）・current_course_no（今日のコース。
  `course.current_course` に `config.today()`）・next_visit（今のコースの次回受診予定日）。
  無ければ null。コースに矛盾があっても一覧は止めない（その患者は null）
- 患者の受診: 印刷済み・期限切れも含めて新しい順。受付番号は消えていれば null。
  report_available はレポートを開ける（受付番号が残っている ready）か
- 患者の記録: 直近 `RECENT_ENTRIES_MAX` 件を新しい順。クローズ回答はコード
  （question_key・value・temperature）のまま返し、表示名は画面で引く。自由記載は有無
  （has_free_text）だけで原文は返さない（原文は D6 の未処理の記載だけに出す）
- 純関数（DB に触れない）。引数は書き換えない
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from tsutae.course import CourseValidationError, current_course
from tsutae.schemas import Course, Entry

__all__ = [
    "RECENT_ENTRIES_MAX",
    "course_summary",
    "entry_summary",
    "patient_visit",
]

RECENT_ENTRIES_MAX = 30


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def course_summary(courses: Sequence[Course], today: date) -> dict[str, Any]:
    """{current_course_no, next_visit}。今日より前に始まったコースが無ければ null。"""
    try:
        current = current_course(courses, today)
    except CourseValidationError:
        current = None
    if current is None:
        return {"current_course_no": None, "next_visit": None}
    return {
        "current_course_no": current.course_no,
        "next_visit": _iso(current.next_visit),
    }


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


def entry_summary(entry: Entry) -> dict[str, Any]:
    """患者の画面の記録1件。自由記載の原文は入れない。"""
    return {
        "id": entry.id,
        "recorded_at": entry.recorded_at.isoformat(),
        "record_date": entry.record_date.isoformat(),
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

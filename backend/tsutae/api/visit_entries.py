"""受付で受け取る記録の本文と検査（plan-device-records §5.5）。

スマホに置いた記録が受付のときだけ届く。外からの入力なので全て検査する:

- 形（`VisitEntryIn`）: ID は UUID か `demo-<数字>`、時刻は時差つき、記録日は時刻の JST の
  日付と同じ、種類は中身と合う。質問の文の写しと仮名ID は送らない（端末にだけ置く）
- 本文（`VisitIn`）: 500 件まで、同じ本文の中に同じ ID が無い。5MB の上限は `body_limit`
- 中身（`received_entries`）: 記録日は範囲内で未来でない。版はこの患者のレジメンの登録済みの版。
  回答は**その記録の版**の質問集に照らす（今の版ではない）

1件でも不正なら全体を 422 にする（呼び出し側は何も保存しない）。範囲は今コースの前のコースの
Day1〜今日（前のコースが無ければ今コースの Day1〜今日）で、今コースが無ければ 409 no_course。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from tsutae import db
from tsutae.api.deps import ApiError
from tsutae.api.skill_questions import version_questions
from tsutae.config import to_jst_date, today
from tsutae.course import CourseValidationError, current_course, previous_course
from tsutae.schemas import AnswerType, ClosedAnswer, EntryCreate, EntryKind
from tsutae.skills import regimen_skill_name

__all__ = [
    "MAX_VISIT_ENTRIES",
    "VISIT_BODY_MAX_BYTES",
    "VisitEntryIn",
    "VisitWindow",
    "received_entries",
    "visit_window_of",
]

MAX_VISIT_ENTRIES = 500
VISIT_BODY_MAX_BYTES = 5 * 1024 * 1024
FREE_TEXT_MAX = 2000  # EntryCreate と同じ（長すぎる本文は専用のコードで返す）
_CLIENT_ENTRY_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|demo-[0-9]{1,9}"
)
_VALUES: dict[AnswerType, frozenset[str]] = {
    "three_level": frozenset({"none", "present", "hard"}),
    "temperature": frozenset({"not_measured", "measured"}),
}


class VisitEntryIn(BaseModel):
    """受付で受け取る記録1件。端末の記録から pid と質問の文の写しを外した形。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_entry_id: str = Field(max_length=64)
    recorded_at: AwareDatetime
    record_date: date
    kind: EntryKind
    by_proxy: bool
    skill_version: str = Field(max_length=128)
    answers: list[ClosedAnswer] = Field(default_factory=list)
    free_text: str | None = Field(default=None, max_length=FREE_TEXT_MAX)

    @field_validator("client_entry_id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _CLIENT_ENTRY_ID.fullmatch(value):
            raise ValueError("client_entry_id の形が違う")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> VisitEntryIn:
        if to_jst_date(self.recorded_at) != self.record_date:
            raise ValueError("record_date が recorded_at の JST の日付と違う")
        if self.as_entry().kind != self.kind:
            raise ValueError("kind が回答・自由記載と合わない")
        return self

    def as_entry(self) -> EntryCreate:
        """保存する形。空の記録・回答の重複は EntryCreate の検査で落ちる。"""
        return EntryCreate(
            too_sick=self.kind == "too_sick",
            by_proxy=self.by_proxy,
            answers=list(self.answers),
            free_text=self.free_text,
        )


def check_unique_ids(entries: list[VisitEntryIn]) -> list[VisitEntryIn]:
    """同じ本文の中に同じ ID があれば ValueError（`VisitIn` の検査）。"""
    ids = [e.client_entry_id for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("同じ本文の中に同じ client_entry_id がある")
    return entries


@dataclass(frozen=True)
class VisitWindow:
    """今コースの番号と、受診で送る記録の範囲（start〜end。両端を含む）。"""

    course_no: int
    start: date
    end: date


def visit_window_of(conn: sqlite3.Connection, pid: str) -> VisitWindow:
    """今日の範囲。今コースが無ければ 409 no_course、コースに矛盾があれば 400。"""
    day = today()
    courses = db.list_courses(conn, pid)
    try:
        course = current_course(courses, day)
        previous = (
            None if course is None else previous_course(courses, course.course_no)
        )
    except CourseValidationError as exc:
        raise ApiError(400, exc.code) from exc
    if course is None:
        raise ApiError(409, "no_course")
    first = previous if previous is not None else course
    return VisitWindow(course.course_no, first.infusion_date, day)


def _answer_types(
    conn: sqlite3.Connection, skill_version: str
) -> dict[str, AnswerType] | None:
    questions = version_questions(conn, skill_version)
    if questions is None:
        return None
    return {q.key: q.answer_type for q in questions}


def _answers_fit(entry: VisitEntryIn, types: dict[str, AnswerType]) -> bool:
    for answer in entry.answers:
        answer_type = types.get(answer.question_key)
        if answer_type is None or answer.value not in _VALUES[answer_type]:
            return False
    return True


def received_entries(
    conn: sqlite3.Connection,
    regimen: str,
    entries: list[VisitEntryIn],
    window: VisitWindow,
) -> list[db.ReceivedEntry]:
    """検査を通った記録を保存の形で返す。1件でも不正なら 422 invalid_input。"""
    prefix = f"{regimen_skill_name(regimen)}@"
    types_by_version: dict[str, dict[str, AnswerType] | None] = {}
    received: list[db.ReceivedEntry] = []
    for item in entries:
        version = item.skill_version
        if version not in types_by_version:
            types_by_version[version] = (
                _answer_types(conn, version) if version.startswith(prefix) else None
            )
        types = types_by_version[version]
        in_window = window.start <= item.record_date <= window.end
        if not in_window or types is None or not _answers_fit(item, types):
            raise ApiError(422, "invalid_input")
        received.append(
            db.ReceivedEntry(
                client_entry_id=item.client_entry_id,
                entry=item.as_entry(),
                recorded_at=item.recorded_at,
                skill_version=version,
            )
        )
    return received

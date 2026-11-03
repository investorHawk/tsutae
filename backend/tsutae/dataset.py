"""合成データ（SyntheticPatient）を DB と同じ型（Entry / Course / EntryCreate）に直す。

評価・テスト・デモ投入で共通に使う。Entry.id は合成データの seq と同じにする
（正解ラベルの entry_seq と、変換の entry_no → entries.id を突き合わせるため）。
"""

from __future__ import annotations

from tsutae.config import to_jst_date
from tsutae.schemas import Course, Entry, EntryCreate, SyntheticEntry, SyntheticPatient


def to_entry_create(src: SyntheticEntry) -> EntryCreate:
    return EntryCreate(
        too_sick=src.too_sick,
        by_proxy=src.by_proxy,
        answers=list(src.answers),
        free_text=src.free_text,
    )


def to_entry(patient_id: str, src: SyntheticEntry) -> Entry:
    created = to_entry_create(src)
    return Entry(
        id=src.seq,
        patient_id=patient_id,
        recorded_at=src.recorded_at,
        record_date=to_jst_date(src.recorded_at),
        kind=created.kind,
        by_proxy=created.by_proxy,
        skill_version=src.skill_version,
        answers=list(created.answers),
        free_text=created.free_text,
    )


def to_entries(patient: SyntheticPatient) -> list[Entry]:
    entries = [to_entry(patient.patient_id, e) for e in patient.entries]
    return sorted(entries, key=lambda e: (e.recorded_at, e.id))


def to_courses(patient: SyntheticPatient) -> list[Course]:
    courses = [
        Course(
            patient_id=patient.patient_id,
            course_no=c.course_no,
            infusion_date=c.infusion_date,
            planned_date=c.planned_date,
            next_visit=c.next_visit,
            note=c.note,
        )
        for c in patient.courses
    ]
    return sorted(courses, key=lambda c: c.course_no)

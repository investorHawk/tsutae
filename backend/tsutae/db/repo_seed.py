"""合成データの投入: 患者・コース・記録を1つのトランザクションで入れる。

途中で失敗すればその患者は丸ごと残らない（次に流せば入れ直せる）。既にいる患者
（仮名IDが同じ）には触らない。確認と挿入は同じトランザクションの1文で行う。

記録は schemas.py の `Entry`（`tsutae.dataset.to_entries` の結果）で受け取る
（§0「共通の型は schemas.py」。db の中に専用の型を作らない）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from tsutae.db.connection import to_jst, write_transaction
from tsutae.db.repo_entries import insert_entry_rows, validate_skill_version
from tsutae.db.repo_patients import (
    insert_patient_row,
    upsert_course_row,
    validate_new_patient,
)
from tsutae.db.repo_record_marks import upsert_mark_row
from tsutae.schemas import BUILTIN_REGIMENS, Course, Entry, EntryCreate


def _to_create(entry: Entry) -> EntryCreate:
    """Entry を add_entry と同じ入力に直す。kind が中身と食い違えば ValueError。"""
    created = EntryCreate(
        too_sick=entry.kind == "too_sick",
        by_proxy=entry.by_proxy,
        answers=list(entry.answers),
        free_text=entry.free_text,
    )
    if created.kind != entry.kind:
        raise ValueError("Entry.kind が回答・自由記載と合わない")
    return created


def _validate(
    patient_id: str,
    regimen: str,
    courses: Sequence[Course],
    entries: Sequence[Entry],
) -> list[EntryCreate]:
    """書く前に全て検査し、記録ごとの EntryCreate を返す。"""
    if regimen not in BUILTIN_REGIMENS:  # 合成データは評価済みの2つだけ
        raise ValueError(f"unknown regimen: {regimen!r}")
    validate_new_patient(regimen, patient_id)
    for course in courses:
        if not isinstance(course, Course) or course.patient_id != patient_id:
            raise ValueError("courses は同じ患者の Course")
    created: list[EntryCreate] = []
    for item in entries:
        if not isinstance(item, Entry) or item.patient_id != patient_id:
            raise ValueError("entries は同じ患者の Entry")
        validate_skill_version(item.skill_version)
        to_jst(item.recorded_at)  # datetime でなければ TypeError
        created.append(_to_create(item))
    return created


def seed_patient(
    conn: sqlite3.Connection,
    *,
    patient_id: str,
    regimen: str,
    courses: Sequence[Course],
    entries: Sequence[Entry],
    marks: Sequence[datetime] = (),
) -> bool:
    """まだいなければ患者・コース・記録を入れて True。

    marks は記録を入れずに付ける日付の印の時刻（スマホ保存の撮影用。§5.10）。

    記録は渡した順に入れ、DB が id を振る（`Entry.id` と `record_date` は使わない。
    record_date は recorded_at から作り直す）。既にいる患者なら何も書かずに False。
    入力が不正なら書く前に ValueError。DB の失敗は rollback してから外へ出す
    （何も残らない）。
    """
    created = _validate(patient_id, regimen, courses, entries)
    with write_transaction(conn):
        if not insert_patient_row(conn, patient_id, regimen, skip_existing=True):
            return False
        for course in courses:
            upsert_course_row(conn, course)
        for item, entry in zip(entries, created, strict=True):
            insert_entry_rows(
                conn, patient_id, entry, item.recorded_at, item.skill_version
            )
        for at in marks:
            upsert_mark_row(conn, patient_id, to_jst(at))
    return True

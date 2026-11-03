"""generate_visit_report の回帰（仕上げのレビュー指摘5・6）。症例は全て合成。

- 5: 受付番号・仮名ID を区切りを省いて・置き換えて書いても、依頼文に入らない
- 6: 書式文字（ゼロ幅空白・BOM・ソフトハイフン）だけの自由記載が1件あっても、
  レポートが作れる（AI の結果でも、AI変換なしでも）
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pipeline_fakes import FakeRunner, label_payloads, standard_steps

from tsutae import db
from tsutae.config import SKILLS_DIR, SYNTHETIC_DIR, get_settings, jst_datetime
from tsutae.dataset import to_courses, to_entry_create
from tsutae.pipeline import prepare_input
from tsutae.pipeline.service import ensure_skill_versions, generate_visit_report
from tsutae.schemas import EntryCreate
from tsutae.skills import load_regimen_skill, load_report_skill
from tsutae.synthetic import load_patient

DEMO = load_patient(SYNTHETIC_DIR / "demo_patient.json")
PID = DEMO.patient_id  # P-DEMO0001
RECEPTION_NO = DEMO.reception_no  # A-023
EXPIRES_AT = jst_datetime(date(2026, 11, 10), 12)
LAST_EVENING = jst_datetime(date(2026, 11, 8), 22)


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")


@pytest.fixture
def conn(tmp_db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_db_path)
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def settings(tmp_db_path: Path) -> Any:
    return replace(get_settings(), db_path=tmp_db_path, skills_dir=SKILLS_DIR)


def _seed(conn: sqlite3.Connection, extra_text: str) -> tuple[int, int]:
    """デモ患者・前夜の追加の自由記載・受診を入れ、(受診 id, 追加の記録 id) を返す。"""
    db.create_patient(conn, DEMO.regimen, patient_id=PID)
    for course in to_courses(DEMO):
        db.upsert_course(conn, course)
    for src in DEMO.entries:
        db.add_entry(
            conn, PID, to_entry_create(src), src.recorded_at, src.skill_version
        )
    extra = db.add_entry(
        conn, PID, EntryCreate(free_text=extra_text), LAST_EVENING, "regimen-folfox@1"
    )
    ensure_skill_versions(conn, SKILLS_DIR)
    vid = db.create_visit(conn, PID, RECEPTION_NO, DEMO.visit_date, EXPIRES_AT, 3)
    return vid, extra.id


@pytest.mark.parametrize(
    "text, needle",
    [
        ("受付はA023番だった", "023"),
        ("IDはPDEMO0001と書いてある", "DEMO0001"),
        ("IDはP DEMO0001", "DEMO0001"),
        ("IDはP_DEMO0001", "DEMO0001"),
        ("受付票はA・023", "023"),
    ],
)
async def test_identifier_without_hyphen_is_not_sent(
    conn: sqlite3.Connection, settings: Any, text: str, needle: str
) -> None:
    vid, extra_id = _seed(conn, text)
    runner = FakeRunner()
    await generate_visit_report(conn, vid, runner=runner, settings=settings)
    assert needle.casefold() not in runner.prompts[0].casefold()
    reasons = {
        u.entry_id: u.reason for u in db.get_timeline(conn, vid).unprocessed_entries
    }
    assert reasons[extra_id] == "known_identifier"


FORMAT_ONLY = ["​", "﻿", "­​"]


@pytest.mark.parametrize("text", FORMAT_ONLY, ids=repr)
async def test_format_characters_only_does_not_fail_the_fallback(
    conn: sqlite3.Connection, settings: Any, text: str
) -> None:
    vid, _ = _seed(conn, text)
    await generate_visit_report(conn, vid, runner=FakeRunner([]), settings=settings)
    visit = db.get_visit(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", 1)
    assert db.get_report(conn, vid) is not None


@pytest.mark.parametrize("text", FORMAT_ONLY, ids=repr)
async def test_format_characters_only_does_not_fail_the_ai_report(
    conn: sqlite3.Connection, settings: Any, text: str
) -> None:
    vid, _ = _seed(conn, text)
    prepared = prepare_input(
        courses=db.list_courses(conn, PID),
        entries=db.list_entries(conn, PID),
        regimen_skill=load_regimen_skill("FOLFOX", SKILLS_DIR),
        report_skill=load_report_skill(skills_dir=SKILLS_DIR),
        visit_date=DEMO.visit_date,
        exclude_literals=(PID, RECEPTION_NO),
    )
    timeline, report = label_payloads("demo_patient", prepared)
    runner = FakeRunner(standard_steps(timeline, report))
    await generate_visit_report(conn, vid, runner=runner, settings=settings)
    visit = db.get_visit(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", 0)

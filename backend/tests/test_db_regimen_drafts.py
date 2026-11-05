"""regimen_drafts・regimen_forms の保存層（architecture 9c「下書き」）。

- 1つのレジメンに開いている（open・working）下書きは1つまで（新規は識別名が決まるまで NULL）
- 書き換えは open のときだけ。working は往復ごとに generation を上げる
- working のまま上限を過ぎた行は open に戻し、会話に失敗の行を残す
- 破棄で chat_json を空にする。regimen_forms は skill_versions の版に結びつく
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tsutae import db
from tsutae.config import JST
from tsutae.db import repo_regimen_drafts as drafts

FORM = '{"basic": {}}'
AT = datetime(2026, 11, 9, 10, 0, tzinfo=JST)


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_db_path)
    db.init_db(c)
    return c


def test_init_db_creates_draft_tables(conn: sqlite3.Connection) -> None:
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"regimen_drafts", "regimen_forms"} <= names


def test_create_and_get(conn: sqlite3.Connection) -> None:
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    got = drafts.get_draft(conn, draft_id)
    assert got is not None
    assert got["id"] == draft_id
    assert got["regimen"] is None and got["base_version"] is None
    assert got["status"] == "open" and got["generation"] == 0
    assert got["form_json"] == FORM and got["sources_json"] == "{}"
    assert got["chat"] == []
    assert got["working_since"] is None
    assert got["created_at"].tzinfo is not None
    assert drafts.get_draft(conn, draft_id + 1) is None


def test_one_active_draft_per_regimen(conn: sqlite3.Connection) -> None:
    first = drafts.create_draft(conn, regimen="FOLFOX", base_version=1, form_json=FORM)
    with pytest.raises(drafts.DraftConflictError) as exc:
        drafts.create_draft(conn, regimen="FOLFOX", base_version=1, form_json=FORM)
    assert exc.value.code == "draft_exists"
    assert drafts.find_active_draft(conn, "FOLFOX")["id"] == first
    # 新規（regimen NULL）はいくつでも
    drafts.create_draft(conn, regimen=None, base_version=None, form_json=FORM)
    drafts.create_draft(conn, regimen=None, base_version=None, form_json=FORM)
    assert drafts.discard_draft(conn, first)
    assert drafts.find_active_draft(conn, "FOLFOX") is None
    drafts.create_draft(conn, regimen="FOLFOX", base_version=1, form_json=FORM)


def test_list_active_drafts(conn: sqlite3.Connection) -> None:
    a = drafts.create_draft(conn, regimen=None, base_version=None, form_json=FORM)
    b = drafts.create_draft(conn, regimen="CAPOX", base_version=1, form_json=FORM)
    c = drafts.create_draft(conn, regimen=None, base_version=None, form_json=FORM)
    drafts.discard_draft(conn, c)
    assert [d["id"] for d in drafts.list_active_drafts(conn)] == [a, b]


def test_update_only_when_open(conn: sqlite3.Connection) -> None:
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    assert drafts.update_draft_form(
        conn,
        draft_id,
        form_json='{"x": 1}',
        sources_json='{"a": "standard"}',
        regimen="FOLFIRI-BV",
    )
    got = drafts.get_draft(conn, draft_id)
    assert got["form_json"] == '{"x": 1}'
    assert got["sources_json"] == '{"a": "standard"}'
    assert got["regimen"] == "FOLFIRI-BV"
    assert drafts.begin_working(conn, draft_id) == 1
    assert not drafts.update_draft_form(
        conn, draft_id, form_json=FORM, sources_json="{}", regimen=None
    )
    assert drafts.get_draft(conn, draft_id)["form_json"] == '{"x": 1}'


def test_update_regimen_conflict(conn: sqlite3.Connection) -> None:
    drafts.create_draft(conn, regimen="FOLFIRI-BV", base_version=None, form_json=FORM)
    other = drafts.create_draft(conn, regimen=None, base_version=None, form_json=FORM)
    with pytest.raises(drafts.DraftConflictError) as exc:
        drafts.update_draft_form(
            conn, other, form_json=FORM, sources_json="{}", regimen="FOLFIRI-BV"
        )
    assert exc.value.code == "code_taken"


def test_begin_working_bumps_generation(conn: sqlite3.Connection) -> None:
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    assert drafts.begin_working(conn, draft_id) == 1
    assert drafts.begin_working(conn, draft_id) is None  # 既に working
    got = drafts.get_draft(conn, draft_id)
    assert got["status"] == "working" and got["working_since"] is not None


def test_recover_stale_working(conn: sqlite3.Connection) -> None:
    stale = drafts.create_draft(conn, regimen=None, base_version=None, form_json=FORM)
    fresh = drafts.create_draft(conn, regimen=None, base_version=None, form_json=FORM)
    drafts.begin_working(conn, stale, at=AT - timedelta(seconds=120))
    drafts.begin_working(conn, fresh, at=AT - timedelta(seconds=30))
    assert drafts.recover_stale_working(conn, timeout_s=90, now=AT) == 1
    got = drafts.get_draft(conn, stale)
    assert got["status"] == "open" and got["working_since"] is None
    assert got["generation"] == 1
    assert got["chat"] == [
        {
            "role": "system",
            "kind": "turn_failed",
            "reason": "timeout",
            "generation": 1,
            "at": AT.isoformat(timespec="microseconds"),
        }
    ]
    assert drafts.get_draft(conn, fresh)["status"] == "working"
    assert drafts.recover_stale_working(conn, timeout_s=90, now=AT) == 0


def test_discard_clears_chat(conn: sqlite3.Connection) -> None:
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    conn.execute(
        "UPDATE regimen_drafts SET chat_json = ? WHERE id = ?",
        ('[{"role": "doctor", "text": "FOLFIRI を作りたい"}]', draft_id),
    )
    conn.commit()
    assert drafts.discard_draft(conn, draft_id)
    got = drafts.get_draft(conn, draft_id)
    assert got["status"] == "discarded" and got["chat"] == []
    assert got["closed_at"] is not None
    assert not drafts.discard_draft(conn, draft_id)  # 閉じた下書きは変えない


def test_discard_refuses_working(conn: sqlite3.Connection) -> None:
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    drafts.begin_working(conn, draft_id)
    assert not drafts.discard_draft(conn, draft_id)
    assert drafts.get_draft(conn, draft_id)["status"] == "working"


def test_adopt_rows_in_one_transaction(conn: sqlite3.Connection) -> None:
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    with db.write_transaction(conn):
        db.insert_skill_version_row(conn, "regimen-x", 1, "text", None)
        drafts.insert_regimen_form_row(conn, "regimen-x", 1, FORM)
        assert drafts.mark_adopted_row(
            conn, draft_id, form_json=FORM, sources_json="{}", adopted_version=1
        )
    got = drafts.get_draft(conn, draft_id)
    assert got["status"] == "adopted" and got["adopted_version"] == 1
    assert got["chat"] == []
    assert drafts.get_regimen_form(conn, "regimen-x", 1) == FORM
    assert drafts.get_regimen_form(conn, "regimen-x", 2) is None


def test_mark_adopted_requires_same_form(conn: sqlite3.Connection) -> None:
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    with db.write_transaction(conn):
        assert not drafts.mark_adopted_row(
            conn,
            draft_id,
            form_json='{"other": 1}',
            sources_json="{}",
            adopted_version=1,
        )
    assert drafts.get_draft(conn, draft_id)["status"] == "open"


def test_regimen_form_needs_skill_version(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError), db.write_transaction(conn):
        drafts.insert_regimen_form_row(conn, "regimen-nope", 1, FORM)


def test_insert_skill_version_row_conflict(conn: sqlite3.Connection) -> None:
    db.save_skill_version(conn, "regimen-x", 1, "text", None)
    with db.write_transaction(conn):
        db.insert_skill_version_row(
            conn, "regimen-x", 1, "text", None
        )  # 同じなら何もしない
    with pytest.raises(ValueError), db.write_transaction(conn):
        db.insert_skill_version_row(conn, "regimen-x", 1, "other", None)


def test_update_needs_the_values_that_were_read(conn: sqlite3.Connection) -> None:
    """読んだ時の form・出どころと違えば書かない（読みと書きの間の割り込みを消さない）。"""
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    assert drafts.update_draft_form(
        conn, draft_id, form_json='{"x": 1}', sources_json="{}", regimen=None
    )
    assert not drafts.update_draft_form(
        conn,
        draft_id,
        form_json='{"x": 2}',
        sources_json="{}",
        regimen=None,
        expected_form_json=FORM,  # 割り込みの前に読んだ値
        expected_sources_json="{}",
    )
    assert drafts.get_draft(conn, draft_id)["form_json"] == '{"x": 1}'
    assert drafts.update_draft_form(
        conn,
        draft_id,
        form_json='{"x": 3}',
        sources_json="{}",
        regimen=None,
        expected_form_json='{"x": 1}',
        expected_sources_json="{}",
    )
    assert drafts.get_draft(conn, draft_id)["form_json"] == '{"x": 3}'


def test_recover_working_from_the_future(conn: sqlite3.Connection) -> None:
    """working_since が今より先（時計の基準が変わった別のプロセス）も取り残された行とみなす。"""
    draft_id = drafts.create_draft(
        conn, regimen=None, base_version=None, form_json=FORM
    )
    drafts.begin_working(conn, draft_id, at=AT + timedelta(hours=22))
    assert drafts.recover_stale_working(conn, timeout_s=90, now=AT) == 1
    assert drafts.get_draft(conn, draft_id)["status"] == "open"

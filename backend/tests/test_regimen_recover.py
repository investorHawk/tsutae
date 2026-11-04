"""採用の途中で止まった下書きを起動時に補う（architecture 9c「確認と採用」のクラッシュ窓）。

採用は「ファイルが先・DB が後」。SKILL.md を置いた後・DB の commit の前にプロセスが落ちると、
起動し直したとき ensure_skill_versions が SKILL.md の版を登録するが、regimen_forms・下書きの
adopted は無い（そのままでは既存は form_unavailable、新規は code_taken で開けなくなる）。

- 開いた下書きを今の値で描いた文が、登録された版の文とバイトで一致すれば、regimen_forms・
  部品集・下書きの adopted を補う（一致しなければ補わず警告に残す）
- 新規でフォルダだけ残った（SKILL.md が無い。一時ファイルだけ）なら、フォルダを消す
- 起動（app.startup）が ensure_skill_versions の後に呼ぶ
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from api_helpers import make_settings
from regimen_fixtures import extra_form, fill_patch

from tsutae import db
from tsutae.api.app import startup
from tsutae.config import SKILLS_HOME
from tsutae.db import repo_regimen_drafts as repo
from tsutae.db.repo_question_library import get_library_question
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen import recover as recover_module
from tsutae.regimen.drafts import (
    create_new_draft,
    draft_form,
    open_skill_draft,
    patch_draft,
)
from tsutae.regimen.edit import FieldChange, FormPatch
from tsutae.regimen.preview import render_draft
from tsutae.regimen.recover import recover_interrupted_adoptions
from tsutae.regimen.source import form_from_skill
from tsutae.skills import load_regimen_skill

TIMEOUT = 90.0
NEW_NAME = "regimen-folfiri-bv"


@dataclass
class Env:
    conn: sqlite3.Connection
    home: Path
    db_path: Path

    @property
    def skills_dir(self) -> Path:
        return self.home / ".claude" / "skills"


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    db_path = tmp_path / "t.db"
    conn = db.connect(db_path)
    db.init_db(conn)
    ensure_skill_versions(conn, home / ".claude" / "skills")
    db.seed_question_library(conn)
    yield Env(conn, home, db_path)
    conn.close()


def _patch(env: Env, draft_id: int, patch: FormPatch) -> dict:
    return patch_draft(
        env.conn, draft_id, patch, skills_dir=env.skills_dir, timeout_s=TIMEOUT
    )


def _filled_new(env: Env) -> dict:
    draft = create_new_draft(env.conn)
    patch = fill_patch(draft_form(draft), extra_form("folfiri_bv"))
    return _patch(env, draft["id"], patch)


def _crash_after_write(env: Env, draft: dict) -> Path:
    """採用が SKILL.md を置いたところで止まった状態（DB には何も書いていない）。"""
    form = draft_form(draft)
    name = draft["regimen"] and f"regimen-{draft['regimen'].lower()}"
    path = env.skills_dir / str(name) / "SKILL.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(render_draft(draft, form), encoding="utf-8")
    return path


def _restart(env: Env) -> int:
    ensure_skill_versions(env.conn, env.skills_dir)
    return recover_interrupted_adoptions(env.conn, env.skills_dir)


def test_existing_adoption_is_completed(env: Env) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    draft = _patch(
        env, draft["id"], FormPatch(changes=(FieldChange("notes", "施設の決まり"),))
    )
    _crash_after_write(env, draft)
    assert _restart(env) == 1
    got = repo.get_draft(env.conn, draft["id"])
    assert got["status"] == "adopted" and got["adopted_version"] == 2
    assert got["chat"] == []
    assert form_from_skill(env.conn, "regimen-folfox", 2).notes == "施設の決まり"
    again, created = open_skill_draft(
        env.conn, "regimen-folfox", skills_dir=env.skills_dir
    )
    assert created and again["base_version"] == 2
    assert _restart(env) == 0  # 何度呼んでもよい


def test_new_adoption_is_completed(env: Env) -> None:
    draft = _filled_new(env)
    _crash_after_write(env, draft)
    assert _restart(env) == 1
    assert repo.get_draft(env.conn, draft["id"])["status"] == "adopted"
    assert load_regimen_skill("FOLFIRI-BV", env.skills_dir).version == 1
    assert form_from_skill(env.conn, NEW_NAME, 1) == draft_form(draft)
    fatigue = get_library_question(env.conn, "fatigue")
    assert fatigue is not None and fatigue["origin"] == "adopted"
    _, created = open_skill_draft(env.conn, NEW_NAME, skills_dir=env.skills_dir)
    assert created


def test_different_text_is_not_completed(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """描いた文が登録された版と違えば（別の書き手の版など）補わない。"""
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    path = _crash_after_write(env, draft)
    path.write_text(
        path.read_text("utf-8").replace("description:", "description: x", 1), "utf-8"
    )
    with caplog.at_level(logging.WARNING, logger=recover_module.__name__):
        assert _restart(env) == 0
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"
    assert repo.get_regimen_form(env.conn, "regimen-folfox", 2) is None
    assert "regimen-folfox" in caplog.text


def test_untouched_drafts_are_left_alone(env: Env) -> None:
    open_skill_draft(env.conn, "regimen-capox", skills_dir=env.skills_dir)
    _filled_new(env)
    create_new_draft(env.conn)  # 識別名がまだ無い
    assert _restart(env) == 0
    assert [d["status"] for d in repo.list_active_drafts(env.conn)] == ["open"] * 3


def test_empty_new_folder_is_removed(env: Env) -> None:
    """mkdir の後・SKILL.md を置く前に止まった（一時ファイルだけ）なら、識別名を空ける。"""
    draft = _filled_new(env)
    folder = env.skills_dir / NEW_NAME
    folder.mkdir()
    (folder / ".SKILL.md.abc123.tmp").write_bytes(b"partial")
    assert _restart(env) == 0
    assert not folder.exists()
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"


def test_new_folder_with_other_files_is_kept(env: Env) -> None:
    _filled_new(env)
    folder = env.skills_dir / NEW_NAME
    folder.mkdir()
    (folder / "notes.txt").write_text("先生のメモ", "utf-8")
    _restart(env)
    assert (folder / "notes.txt").exists()


def test_startup_completes_an_interrupted_adoption(env: Env, tmp_path: Path) -> None:
    draft = _filled_new(env)
    _crash_after_write(env, draft)
    settings = replace(
        make_settings(tmp_path), db_path=env.db_path, skills_dir=env.skills_dir
    )
    startup(settings)
    assert repo.get_draft(env.conn, draft["id"])["status"] == "adopted"
    assert repo.get_regimen_form(env.conn, NEW_NAME, 1) is not None


def test_broken_draft_does_not_stop_recovery(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """読めない下書きが1件あっても起動を止めず、他の下書きは補う（ensure_skill_versions と同じ方針）。"""
    broken, _ = open_skill_draft(env.conn, "regimen-capox", skills_dir=env.skills_dir)
    env.conn.execute(
        "UPDATE regimen_drafts SET form_json = ? WHERE id = ?",
        ("not json", broken["id"]),
    )
    env.conn.commit()
    draft = _filled_new(env)
    _crash_after_write(env, draft)
    with caplog.at_level(logging.WARNING, logger=recover_module.__name__):
        assert _restart(env) == 1
    assert repo.get_draft(env.conn, draft["id"])["status"] == "adopted"
    assert f"draft={broken['id']}" in caplog.text
    assert "not json" not in caplog.text


def test_schedule_locked_adoption_is_not_completed(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """adopt が断る「患者のいるレジメンの日程の変更」は、回復でも確定しない。"""
    db.create_patient(env.conn, "FOLFOX")
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    draft = _patch(
        env,
        draft["id"],
        FormPatch(changes=(FieldChange("basic.cycle_days", 21),)),
    )
    _crash_after_write(env, draft)
    with caplog.at_level(logging.WARNING, logger=recover_module.__name__):
        assert _restart(env) == 0
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"
    assert repo.get_regimen_form(env.conn, "regimen-folfox", 2) is None
    assert "schedule_locked" in caplog.text

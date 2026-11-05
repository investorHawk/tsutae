"""採用・直接編集の割り込みと後始末（検証で挙がった問題。architecture 9c「確認と採用」）。

- 確認の印に ASCII 以外の文字が来ても token_mismatch（500 にしない）
- 確かめた後に患者が入ったら、採用の直前（同じトランザクション）でも schedule_locked
- 採用の途中で別の書き手が破棄・working にしたら、その理由（not_open・working）を返す
- 新規の書き込みの失敗は write_error。後始末で消せないフォルダは警告に残す
- PATCH の読みと書きの間に別の書き手が変えたら conflict（割り込んだ値を消さない）
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from regimen_fixtures import extra_form, fill_patch

from tsutae import db
from tsutae.config import SKILLS_HOME
from tsutae.db import repo_regimen_drafts as repo
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen import adopt as adopt_module
from tsutae.regimen import drafts as drafts_module
from tsutae.regimen.adopt import adopt
from tsutae.regimen.drafts import (
    DraftError,
    create_new_draft,
    draft_form,
    load_draft,
    open_skill_draft,
    patch_draft,
)
from tsutae.regimen.edit import FieldChange, FormPatch
from tsutae.regimen.preview import build_preview
from tsutae.skills import load_regimen_skill, read_skill_text

TIMEOUT = 90.0
NEW_DIR = "regimen-folfiri-bv"


@dataclass
class Env:
    conn: sqlite3.Connection
    home: Path

    @property
    def skills_dir(self) -> Path:
        return self.home / ".claude" / "skills"


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    conn = db.connect(tmp_path / "t.db")
    db.init_db(conn)
    ensure_skill_versions(conn, home / ".claude" / "skills")
    db.seed_question_library(conn)
    yield Env(conn, home)
    conn.close()


def _patch(env: Env, draft_id: int, patch: FormPatch) -> dict:
    return patch_draft(
        env.conn, draft_id, patch, skills_dir=env.skills_dir, timeout_s=TIMEOUT
    )


def _filled_new(env: Env) -> dict:
    draft = create_new_draft(env.conn)
    patch = fill_patch(draft_form(draft), extra_form("folfiri_bv"))
    return _patch(env, draft["id"], patch)


def _token(env: Env, draft_id: int) -> str:
    draft = load_draft(env.conn, draft_id, timeout_s=TIMEOUT)
    return build_preview(env.conn, draft, skills_dir=env.skills_dir)["confirm_token"]


def _adopt(env: Env, draft_id: int, token: object):
    return adopt(
        env.conn, draft_id, token, True, skills_home=env.home, timeout_s=TIMEOUT
    )


def _after_plan(monkeypatch: pytest.MonkeyPatch, action) -> None:
    """検査（_plan）の後・書き込みの前に別の書き手が動いたことにする。"""
    real_plan = adopt_module._plan

    def plan_then(*args, **kwargs):
        plan = real_plan(*args, **kwargs)
        action()
        return plan

    monkeypatch.setattr(adopt_module, "_plan", plan_then)


def _folfox_cycle_21(env: Env) -> dict:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    return _patch(
        env, draft["id"], FormPatch(changes=(FieldChange("basic.cycle_days", 21),))
    )


# --- 確認の印 ----------------------------------------------------------------------


@pytest.mark.parametrize("token", ["あ", "印" * 64, "é"])
def test_non_ascii_token_is_a_mismatch(env: Env, token: str) -> None:
    draft = _filled_new(env)
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert exc.value.code == "token_mismatch"
    assert not (env.skills_dir / NEW_DIR).exists()


# --- 採用の直前のやり直し ---------------------------------------------------------------


def test_schedule_is_rechecked_just_before_writing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = read_skill_text("regimen-folfox", env.skills_dir)
    draft = _folfox_cycle_21(env)
    token = _token(env, draft["id"])  # 患者がいない間に確かめた
    _after_plan(monkeypatch, lambda: db.create_patient(env.conn, "FOLFOX"))
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert exc.value.code == "schedule_locked"
    assert exc.value.issues[0].field_id == "basic.cycle_days"
    assert read_skill_text("regimen-folfox", env.skills_dir) == before
    assert load_regimen_skill("FOLFOX", env.skills_dir).version == 1
    assert db.get_skill_version(env.conn, "regimen-folfox", 2) is None
    assert repo.get_regimen_form(env.conn, "regimen-folfox", 2) is None
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"


@pytest.mark.parametrize(
    ("action", "code", "status"),
    [
        (repo.discard_draft, "not_open", "discarded"),
        (repo.begin_working, "working", "working"),
    ],
)
def test_adopt_reports_why_the_draft_closed(
    env: Env, monkeypatch: pytest.MonkeyPatch, action, code: str, status: str
) -> None:
    draft = _filled_new(env)
    token = _token(env, draft["id"])
    _after_plan(monkeypatch, lambda: action(env.conn, draft["id"]))
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert exc.value.code == code
    assert repo.get_draft(env.conn, draft["id"])["status"] == status
    assert not (env.skills_dir / NEW_DIR).exists()
    assert db.get_skill_version(env.conn, NEW_DIR, 1) is None


def test_existing_adopt_restores_when_discarded_meanwhile(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = read_skill_text("regimen-capox", env.skills_dir)
    draft, _ = open_skill_draft(env.conn, "regimen-capox", skills_dir=env.skills_dir)
    _patch(env, draft["id"], FormPatch(changes=(FieldChange("notes", "x"),)))
    token = _token(env, draft["id"])
    _after_plan(monkeypatch, lambda: repo.discard_draft(env.conn, draft["id"]))
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert exc.value.code == "not_open"
    assert read_skill_text("regimen-capox", env.skills_dir) == before


# --- 新規の書き込みの失敗と後始末 ---------------------------------------------------------


def test_new_write_failure_is_write_error(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _filled_new(env)
    token = _token(env, draft["id"])

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(adopt_module, "write_atomic", broken)
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert exc.value.code == "write_error"
    assert not (env.skills_dir / NEW_DIR).exists()
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"


def test_cleanup_removes_leftover_temp_files(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一時ファイルが残っても（書き込みの途中で止まった）、フォルダごと消す。"""
    draft = _filled_new(env)
    token = _token(env, draft["id"])

    def partial(path: Path, _data: bytes) -> None:
        (path.parent / f".{path.name}.abc123.tmp").write_bytes(b"x")
        raise OSError("disk full")

    monkeypatch.setattr(adopt_module, "write_atomic", partial)
    with pytest.raises(DraftError):
        _adopt(env, draft["id"], token)
    assert not (env.skills_dir / NEW_DIR).exists()


def test_cleanup_keeps_foreign_files_and_warns(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """自分の書いていないファイルは消さない。消せなかったフォルダは警告に残す。"""
    draft = _filled_new(env)
    token = _token(env, draft["id"])

    def foreign(path: Path, _data: bytes) -> None:
        (path.parent / ".DS_Store").write_bytes(b"x")
        raise OSError("disk full")

    monkeypatch.setattr(adopt_module, "write_atomic", foreign)
    with (
        caplog.at_level(logging.WARNING, logger=adopt_module.__name__),
        pytest.raises(DraftError),
    ):
        _adopt(env, draft["id"], token)
    assert (env.skills_dir / NEW_DIR / ".DS_Store").exists()
    assert not (env.skills_dir / NEW_DIR / "SKILL.md").exists()
    assert NEW_DIR in caplog.text


# --- PATCH の読みと書きの間 ---------------------------------------------------------------


def test_patch_does_not_overwrite_a_concurrent_change(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = create_new_draft(env.conn)
    real_apply = drafts_module.apply_patch

    def apply_then_interleave(*args, **kwargs):
        result = real_apply(*args, **kwargs)
        interleaved = FormPatch(changes=(FieldChange("notes", "割り込んだ値"),))
        monkeypatch.setattr(drafts_module, "apply_patch", real_apply)
        _patch(env, draft["id"], interleaved)  # 例: Claude の往復の結果
        return result

    monkeypatch.setattr(drafts_module, "apply_patch", apply_then_interleave)
    patch = FormPatch(changes=(FieldChange("basic.display_name", "新しい名前"),))
    with pytest.raises(DraftError) as exc:
        _patch(env, draft["id"], patch)
    assert exc.value.code == "conflict"
    form = draft_form(repo.get_draft(env.conn, draft["id"]))
    assert form.notes == "割り込んだ値"
    assert form.basic.display_name is None

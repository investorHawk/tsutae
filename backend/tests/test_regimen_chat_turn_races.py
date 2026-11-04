"""往復の読みと begin_working の間に入った PATCH（T94 の確かめ直し）。

往復は下書きを読んでから依頼文を作り、H1 を掛けてから begin_working する。この間に
先生の PATCH（別のスレッド）が入ると、往復の結果は PATCH より前の値から作ったフォームで
上書きし、PATCH の値と出どころ doctor_edit が黙って消える。begin_working は「読んだ時と
同じ form_json・sources_json」のときだけ working にし、違えば 409 conflict にする
（PATCH の側の `update_draft_form` の expected_* と対になる）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from regimen_chat_fakes import ScriptChat, change

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.db import repo_regimen_drafts as repo
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen import chat_turn
from tsutae.regimen.chat_turn import run_turn
from tsutae.regimen.drafts import (
    DraftError,
    create_new_draft,
    draft_form,
    patch_draft,
)
from tsutae.regimen.edit import FieldChange, FormPatch


@dataclass
class Env:
    conn: sqlite3.Connection
    db_path: Path
    skills_dir: Path


@pytest.fixture
def env(tmp_path: Path, fixed_today: str) -> Iterator[Env]:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    path = tmp_path / "t.db"
    conn = db.connect(path)
    db.init_db(conn)
    skills_dir = home / ".claude" / "skills"
    ensure_skill_versions(conn, skills_dir)
    db.seed_question_library(conn)
    yield Env(conn, path, skills_dir)
    conn.close()


def _run(env: Env, draft_id: int, chat: Any) -> Any:
    return asyncio.run(
        run_turn(
            env.conn,
            draft_id,
            "1コースは14日",
            chat=chat,
            settings=dataclasses.replace(get_settings()),
            skills_dir=env.skills_dir,
        )
    )


def test_patch_between_read_and_begin_working_is_conflict(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = create_new_draft(env.conn)
    real = chat_turn.build_turn_prompt

    def prompt_then_patch(start: Any, text: str) -> str:
        other = db.connect(env.db_path)
        try:
            patch_draft(
                other,
                draft["id"],
                FormPatch(changes=(FieldChange("basic.display_name", "FOLFIRI＋BV"),)),
                skills_dir=env.skills_dir,
                timeout_s=90,
            )
        finally:
            other.close()
        return real(start, text)

    monkeypatch.setattr(chat_turn, "build_turn_prompt", prompt_then_patch)
    chat = ScriptChat([change("basic.cycle_days", 14)])
    with pytest.raises(DraftError) as info:
        _run(env, draft["id"], chat)
    assert info.value.code == "conflict"
    assert chat.seen == []
    got = repo.get_draft(env.conn, draft["id"])
    assert got["status"] == "open" and got["generation"] == 0
    assert draft_form(got).basic.display_name == "FOLFIRI＋BV"
    assert '"basic.display_name":"doctor_edit"' in got["sources_json"]
    assert got["chat"] == []


def test_begin_working_checks_expected_values(env: Env) -> None:
    draft = create_new_draft(env.conn)
    form_json, sources_json = draft["form_json"], draft["sources_json"]
    assert (
        repo.begin_working(
            env.conn,
            draft["id"],
            expected_form_json=form_json,
            expected_sources_json='{"basic.target":"standard"}',
        )
        is None
    )
    assert (
        repo.begin_working(
            env.conn,
            draft["id"],
            expected_form_json=form_json + " ",
            expected_sources_json=sources_json,
        )
        is None
    )
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"
    assert (
        repo.begin_working(
            env.conn,
            draft["id"],
            expected_form_json=form_json,
            expected_sources_json=sources_json,
        )
        == 1
    )

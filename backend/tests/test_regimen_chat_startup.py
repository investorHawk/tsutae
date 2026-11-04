"""起動の順（T94）: working の取り残しを open に戻してから、採用の途中の回復を行う。

起動の時点で working の下書きは全て前のプロセスの往復の取り残し（単一プロセス）。
戻さずに `recover_interrupted_adoptions`（open だけを見る）を呼ぶと、working のまま
落ちた下書きが回復から漏れる（T93 の確かめ直しの指摘）。
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

from api_helpers import make_settings
from regimen_fixtures import extra_form, fill_patch

from tsutae import db
from tsutae.api.app import startup
from tsutae.config import SKILLS_HOME, Settings
from tsutae.db import repo_regimen_drafts as repo
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen.drafts import create_new_draft, draft_form, patch_draft
from tsutae.regimen.preview import render_draft
from tsutae.regimen.recover import recover_abandoned_turns


def _setup(tmp_path: Path) -> tuple[sqlite3.Connection, Path, Settings]:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    skills_dir = home / ".claude" / "skills"
    db_path = tmp_path / "t.db"
    conn = db.connect(db_path)
    db.init_db(conn)
    ensure_skill_versions(conn, skills_dir)
    db.seed_question_library(conn)
    settings = replace(make_settings(tmp_path), db_path=db_path, skills_dir=skills_dir)
    return conn, skills_dir, settings


def test_recover_abandoned_turns_takes_every_working_draft(
    tmp_path: Path, fixed_today: str
) -> None:
    conn, _, _ = _setup(tmp_path)
    working = create_new_draft(conn)
    other = create_new_draft(conn)
    repo.begin_working(conn, working["id"])  # 今始まったばかりでも取り残し
    assert recover_abandoned_turns(conn) == 1
    got = repo.get_draft(conn, working["id"])
    assert got["status"] == "open" and got["working_since"] is None
    assert got["chat"][-1]["kind"] == "turn_failed"
    assert repo.get_draft(conn, other["id"])["chat"] == []
    assert recover_abandoned_turns(conn) == 0
    conn.close()


def test_startup_recovers_working_before_interrupted_adoption(
    tmp_path: Path, fixed_today: str
) -> None:
    conn, skills_dir, settings = _setup(tmp_path)
    draft = create_new_draft(conn)
    draft = patch_draft(
        conn,
        draft["id"],
        fill_patch(draft_form(draft), extra_form("folfiri_bv")),
        skills_dir=skills_dir,
        timeout_s=90,
    )
    # 採用が SKILL.md を置いたところで止まり、その下書きが working のまま残った
    path = skills_dir / "regimen-folfiri-bv" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(render_draft(draft, draft_form(draft)), encoding="utf-8")
    repo.begin_working(conn, draft["id"])
    startup(settings)
    got = repo.get_draft(conn, draft["id"])
    assert got["status"] == "adopted"
    assert repo.get_regimen_form(conn, "regimen-folfiri-bv", 1) is not None
    conn.close()

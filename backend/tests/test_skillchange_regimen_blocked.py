"""T95: 旧 D4（一文 → 差分 → 承認）は report-format だけ。regimen-* は 400 use_regimen_editor。

- `request_change` は regimen-* を `SkillChangeError("use_regimen_editor")` で断る（行を作らず、
  editor を呼ばない。本体の SKILL.md も変えない）
- `POST /api/doctor/skill-changes` は 400 `{"error": "use_regimen_editor"}`
- report-format-default は今のまま依頼できる
- T95 より前に作られた pending の regimen-* の変更も `approve_change` で承認しない
  （failed・use_regimen_editor にして本体も skill_versions も変えない。却下はできる）
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from api_helpers import FakeEditor, api_client, db_conn, login_doctor

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.skillchange import (
    BAD_REQUEST_CODES,
    SkillChangeError,
    approve_change,
    reject_change,
    request_change,
)
from tsutae.skillchange.diff import unified


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


def test_code_is_bad_request() -> None:
    assert "use_regimen_editor" in BAD_REQUEST_CODES


@pytest.mark.parametrize(
    "name", ["regimen-folfox", "regimen-capox", "regimen-ram-wptx"]
)
async def test_request_change_rejects_regimen(
    tmp_db_path: Path, home: Path, name: str
) -> None:
    conn = db.connect(tmp_db_path)
    db.init_db(conn)
    editor = FakeEditor(transform=lambda t: t + "x")
    before = (home / ".claude/skills/regimen-folfox/SKILL.md").read_bytes()
    with pytest.raises(SkillChangeError) as exc:
        await request_change(
            conn,
            name,
            "下痢の質問を直して",
            editor=editor,
            settings=get_settings(),
            skills_home=home,
        )
    assert exc.value.code == "use_regimen_editor"
    assert editor.calls == []
    assert db.list_skill_changes(conn) == []
    assert (home / ".claude/skills/regimen-folfox/SKILL.md").read_bytes() == before


def test_api_rejects_regimen_skill_change(
    tmp_path: Path, home: Path, fixed_today: str
) -> None:
    editor = FakeEditor()
    with api_client(
        tmp_path, editor=editor, skills_dir=home / ".claude" / "skills"
    ) as client:
        login_doctor(client)
        r = client.post(
            "/api/doctor/skill-changes",
            json={"skill_name": "regimen-folfox", "request_text": "下痢の質問を直して"},
        )
        with db_conn(client.app) as conn:
            assert db.list_skill_changes(conn) == []
    assert r.status_code == 400
    assert r.json() == {"error": "use_regimen_editor"}
    assert editor.calls == []


def test_api_still_accepts_report_format(
    tmp_path: Path, home: Path, fixed_today: str
) -> None:
    editor = FakeEditor(
        transform=lambda t: t.replace("quotes_max_items: 30", "quotes_max_items: 20")
    )
    with api_client(
        tmp_path, editor=editor, skills_dir=home / ".claude" / "skills"
    ) as client:
        login_doctor(client)
        r = client.post(
            "/api/doctor/skill-changes",
            json={
                "skill_name": "report-format-default",
                "request_text": "引用は20件まで",
            },
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    assert "+quotes_max_items: 20" in r.json()["diff"]


def _old_pending(conn, home: Path) -> int:
    """T95 より前の旧 D4 で作られた regimen-folfox の pending（diff・new_text つき）。"""
    path = home / ".claude/skills/regimen-folfox/SKILL.md"
    current = path.read_text("utf-8")
    new_text = current.replace("下痢はありましたか", "お腹がゆるくなりましたか")
    assert new_text != current
    return db.create_skill_change(
        conn,
        "regimen-folfox",
        "下痢の質問を直して",
        1,
        diff=unified(current, new_text, path="regimen-folfox/SKILL.md"),
        new_text=new_text,
    )


def test_approve_rejects_old_pending_regimen_change(
    tmp_db_path: Path, home: Path
) -> None:
    conn = db.connect(tmp_db_path)
    db.init_db(conn)
    change_id = _old_pending(conn, home)
    path = home / ".claude/skills/regimen-folfox/SKILL.md"
    before = path.read_bytes()
    with pytest.raises(SkillChangeError) as exc:
        approve_change(conn, change_id, skills_home=home)
    assert exc.value.code == "use_regimen_editor"
    change = db.get_skill_change(conn, change_id)
    assert (change["status"], change["error_code"]) == (
        "failed",
        "use_regimen_editor",
    )
    assert path.read_bytes() == before
    assert db.get_skill_version(conn, "regimen-folfox", 2) is None


def test_old_pending_regimen_change_can_be_rejected(
    tmp_db_path: Path, home: Path
) -> None:
    conn = db.connect(tmp_db_path)
    db.init_db(conn)
    change_id = _old_pending(conn, home)
    reject_change(conn, change_id, skills_home=home)
    assert db.get_skill_change(conn, change_id)["status"] == "rejected"

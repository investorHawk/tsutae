"""T95: 記録の版の解決（`questions_by_version`）が FOLFOX/CAPOX 以外の regimen-* も引く。

- 版の文字列 `regimen-ram-wptx@1` を受け、登録済みならその質問集を返す
- 版を渡さないときは skill_versions にある全ての regimen-* を引く（report-format は引かない）
- `db.list_skill_names(conn, prefix)` は登録済みの Skill 名（重複なし・名前順）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from regimen_fixtures import extra_form

from tsutae import db
from tsutae.config import SKILLS_DIR
from tsutae.pipeline.service import ensure_skill_versions, questions_by_version
from tsutae.regimen import render_regimen_skill
from tsutae.skills import validate_skill_text


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_db_path)
    db.init_db(c)
    return c


def _save_ram(conn: sqlite3.Connection, version: int) -> list:
    text = render_regimen_skill(extra_form("ram_wptx"), version)
    skill = validate_skill_text("regimen-ram-wptx", text)
    questions = list(skill.questions)
    db.save_skill_version(conn, "regimen-ram-wptx", version, text, questions)
    return questions


def test_list_skill_names(conn: sqlite3.Connection) -> None:
    assert db.list_skill_names(conn, "regimen-") == []
    ensure_skill_versions(conn, SKILLS_DIR)
    _save_ram(conn, 1)
    _save_ram(conn, 2)
    assert db.list_skill_names(conn, "regimen-") == [
        "regimen-capox",
        "regimen-folfox",
        "regimen-ram-wptx",
    ]
    assert db.list_skill_names(conn, "report-format-") == ["report-format-default"]
    assert db.list_skill_names(conn, "regimen_%") == []  # LIKE の記号は文字のまま


def test_versions_of_adopted_regimen_are_resolved(conn: sqlite3.Connection) -> None:
    v1 = _save_ram(conn, 1)
    got = questions_by_version(
        conn,
        versions=["regimen-ram-wptx@1", "regimen-ram-wptx@9", "regimen-Bad@1"],
    )
    assert got == {"regimen-ram-wptx@1": v1}


def test_scan_includes_adopted_regimens(conn: sqlite3.Connection) -> None:
    ensure_skill_versions(conn, SKILLS_DIR)
    v1 = _save_ram(conn, 1)
    v2 = _save_ram(conn, 2)
    got = questions_by_version(conn)
    assert got["regimen-ram-wptx@1"] == v1
    assert got["regimen-ram-wptx@2"] == v2
    assert "regimen-folfox@1" in got and "regimen-capox@1" in got
    assert not any(k.startswith("report-format") for k in got)


def test_regimen_skills_by_version(conn: sqlite3.Connection) -> None:
    from tsutae.pipeline.versions import regimen_skills_by_version

    ensure_skill_versions(conn, SKILLS_DIR)
    _save_ram(conn, 1)
    got = regimen_skills_by_version(
        conn,
        [
            "regimen-ram-wptx@1",
            "regimen-folfox@1",
            "regimen-ram-wptx@9",  # 登録されていない版は引かない
            "report-format-default@1",  # regimen でない
            "regimen-Bad@1",
        ],
    )
    assert sorted(got) == ["regimen-folfox@1", "regimen-ram-wptx@1"]
    ram = got["regimen-ram-wptx@1"]
    assert ram.skill_version == "regimen-ram-wptx@1"
    assert (ram.term_keys or {})["倦怠感"] == "fatigue"
    assert got["regimen-folfox@1"].term_keys is None


def test_regimen_skills_by_version_skips_broken_text(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    from tsutae.pipeline.versions import regimen_skills_by_version

    db.save_skill_version(conn, "regimen-ram-wptx", 1, "---\nname: x\n---\n", [])
    assert regimen_skills_by_version(conn, ["regimen-ram-wptx@1"]) == {}
    assert "regimen-ram-wptx@1" in caplog.text


def test_regimen_skills_by_version_warns_on_version_mismatch(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    # 全文の frontmatter の版が skill_versions の版と違う（検査は通る）。黙って落とさない
    from tsutae.pipeline.versions import regimen_skills_by_version

    text = render_regimen_skill(extra_form("ram_wptx"), 1).replace(
        "version: 1", "version: 9"
    )
    assert validate_skill_text("regimen-ram-wptx", text).version == 9
    db.save_skill_version(conn, "regimen-ram-wptx", 1, text, [])
    caplog.set_level("WARNING", logger="tsutae.pipeline.versions")
    assert regimen_skills_by_version(conn, ["regimen-ram-wptx@1"]) == {}
    assert "regimen-ram-wptx@1" in caplog.text
    assert "だるさ" not in caplog.text

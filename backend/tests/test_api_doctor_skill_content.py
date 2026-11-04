"""医師 API: Skill の今の中身（D4 の設定画面で、依頼の前に見せる。読み取り専用）。

- `GET /api/doctor/skills/{name}` は `{name, version, description, questions, text}`
  （questions は regimen の質問の一覧、report-format は空。text は SKILL.md の全文）
- 名前は Skill 名の書式と、skills_dir に置かれた Skill の一覧（許可リスト）で検査する。
  書式の違う名前は 400 invalid_name、置かれていない名前は 404 unknown_skill。
  skills_dir の外を指すシンボリックリンクは 400 invalid_name（任意のファイルを読ませない）
- 壊れた SKILL.md は `SkillValidationError` の code（format は 409）

skills_home は tmp_path に backend/skills_home を写して使う（本物を書き換えない）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from api_helpers import api_client, login_doctor
from fastapi.testclient import TestClient

from tsutae.config import SKILLS_HOME

FOLFOX_KEYS = ["numbness", "diarrhea", "stomatitis", "nausea_appetite", "fever"]
SECRET = "外に置いた秘密のファイル（読ませてはいけない）"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


@pytest.fixture
def skills(home: Path) -> Path:
    return home / ".claude" / "skills"


@pytest.fixture
def client(tmp_path: Path, skills: Path, fixed_today: str):
    with api_client(tmp_path, skills_dir=skills) as c:
        login_doctor(c)
        yield c


def _get(client: TestClient, name: str):
    return client.get(f"/api/doctor/skills/{name}")


def test_regimen_skill_content(client: TestClient, skills: Path) -> None:
    r = _get(client, "regimen-folfox")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"name", "version", "description", "questions", "text"}
    assert body["name"] == "regimen-folfox"
    assert body["version"] == 1
    assert body["description"].startswith("FOLFOX")
    assert [q["key"] for q in body["questions"]] == FOLFOX_KEYS
    assert body["questions"][1] == {
        "key": "diarrhea",
        "text": "下痢はありましたか",
        "answer_type": "three_level",
    }
    file = skills / "regimen-folfox" / "SKILL.md"
    assert body["text"] == file.read_text(encoding="utf-8")


def test_report_format_skill_has_no_questions(client: TestClient) -> None:
    body = _get(client, "report-format-default").json()
    assert body["name"] == "report-format-default"
    assert body["questions"] == []
    assert body["text"].startswith("---\nname: report-format-default\n")


def test_unknown_skill_is_404(client: TestClient) -> None:
    r = _get(client, "regimen-nope")
    assert (r.status_code, r.json()) == (404, {"error": "unknown_skill"})


def test_dir_without_skill_md_is_404(client: TestClient, skills: Path) -> None:
    (skills / "regimen-empty").mkdir()
    r = _get(client, "regimen-empty")
    assert (r.status_code, r.json()) == (404, {"error": "unknown_skill"})


@pytest.mark.parametrize(
    "name",
    ["Regimen-folfox", "regimen_folfox", "etc", "SKILL.md", "regimen-folfox.md"],
)
def test_bad_name_is_400(client: TestClient, name: str) -> None:
    r = _get(client, name)
    assert (r.status_code, r.json()) == (400, {"error": "invalid_name"})


@pytest.mark.parametrize(
    "path",
    [
        "/api/doctor/skills/..%2F..%2Fpytest.ini",
        "/api/doctor/skills/%2E%2E",
        "/api/doctor/skills/regimen-folfox%2FSKILL.md",
    ],
)
def test_path_tricks_do_not_read_files(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code in (400, 404)
    assert "text" not in r.json()


def test_symlinked_dir_outside_is_rejected(
    client: TestClient, skills: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside" / "regimen-evil"
    outside.mkdir(parents=True)
    (outside / "SKILL.md").write_text(f"---\nname: regimen-evil\n---\n{SECRET}\n")
    (skills / "regimen-evil").symlink_to(outside, target_is_directory=True)
    r = _get(client, "regimen-evil")
    assert (r.status_code, r.json()) == (400, {"error": "invalid_name"})
    assert SECRET not in r.text


def test_symlinked_file_outside_is_rejected(
    client: TestClient, skills: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text(SECRET, encoding="utf-8")
    target = skills / "regimen-folfox" / "SKILL.md"
    target.unlink()
    target.symlink_to(secret)
    r = _get(client, "regimen-folfox")
    assert (r.status_code, r.json()) == (400, {"error": "invalid_name"})
    assert SECRET not in r.text


def test_broken_skill_is_409_with_code(client: TestClient, skills: Path) -> None:
    (skills / "regimen-folfox" / "SKILL.md").write_text("本文だけ\n", "utf-8")
    r = _get(client, "regimen-folfox")
    assert (r.status_code, r.json()) == (409, {"error": "format"})


def test_needs_doctor_login(tmp_path: Path, skills: Path, fixed_today: str) -> None:
    with api_client(tmp_path, skills_dir=skills) as c:
        r = _get(c, "regimen-folfox")
    assert (r.status_code, r.json()) == (401, {"error": "not_logged_in"})

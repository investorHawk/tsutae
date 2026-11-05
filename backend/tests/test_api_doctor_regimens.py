"""T95: 医師 API のレジメンの一覧（GET /api/doctor/regimens）と患者の登録の照合。

- 一覧は置かれていて検査に通るレジメン（識別名・Skill 名・版・表示名）。評価済みの2つが先
- POST /patients は一覧にある識別名だけを受ける（無ければ 422 invalid_input。書式の誤りと同じ）
- 壊れた regimen-* は一覧に出ず、その識別名では登録できない
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from api_helpers import api_client, db_conn, login_doctor
from regimen_fixtures import extra_form

from tsutae import db
from tsutae.config import SKILLS_DIR
from tsutae.regimen import render_regimen_skill

BUILTINS = [
    {
        "code": "FOLFOX",
        "skill_name": "regimen-folfox",
        "version": 1,
        "display_name": "FOLFOX",
    },
    {
        "code": "CAPOX",
        "skill_name": "regimen-capox",
        "version": 1,
        "display_name": "CAPOX",
    },
]


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    dst = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, dst)
    return dst


def _place(skills_dir: Path, name: str, text: str) -> None:
    (skills_dir / name).mkdir()
    (skills_dir / name / "SKILL.md").write_text(text, encoding="utf-8")


def test_regimens_requires_doctor(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path) as client:
        r = client.get("/api/doctor/regimens")
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


def test_builtin_regimens(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path) as client:
        login_doctor(client)
        r = client.get("/api/doctor/regimens")
    assert r.status_code == 200
    assert r.json() == {"regimens": BUILTINS}


def test_placed_regimen_is_listed_and_registrable(
    tmp_path: Path, skills_dir: Path, fixed_today: str
) -> None:
    _place(
        skills_dir,
        "regimen-folfiri-bv",
        render_regimen_skill(extra_form("folfiri_bv"), 1),
    )
    with api_client(tmp_path, skills_dir=skills_dir) as client:
        login_doctor(client)
        listed = client.get("/api/doctor/regimens").json()["regimens"]
        r = client.post("/api/doctor/patients", json={"regimen": "FOLFIRI-BV"})
        assert r.status_code == 200, r.text
        with db_conn(client.app) as conn:
            assert db.get_patient(conn, r.json()["id"])["regimen"] == "FOLFIRI-BV"
    assert listed[2] == {
        "code": "FOLFIRI-BV",
        "skill_name": "regimen-folfiri-bv",
        "version": 1,
        "display_name": "FOLFIRI＋BV",
    }


@pytest.mark.parametrize("code", ["XELOX", "FOLFIRI-BV", "BROKEN"])
def test_unlisted_regimen_is_422(
    tmp_path: Path, skills_dir: Path, fixed_today: str, code: str
) -> None:
    _place(skills_dir, "regimen-broken", "---\nname: regimen-broken\n---\n")
    with api_client(tmp_path, skills_dir=skills_dir) as client:
        login_doctor(client)
        codes = [
            g["code"] for g in client.get("/api/doctor/regimens").json()["regimens"]
        ]
        r = client.post("/api/doctor/patients", json={"regimen": code})
        with db_conn(client.app) as conn:
            assert db.list_patients(conn) == []
    assert codes == ["FOLFOX", "CAPOX"]
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


def test_regimen_without_registered_version_is_not_registrable(
    tmp_path: Path, skills_dir: Path, fixed_today: str
) -> None:
    """SKILL.md はあるが skill_versions に版が無い（採用の途中・起動の後に置いた）レジメン。

    新規の採用はファイルが先・DB が後なので、その間に登録すると、DB が落ちてフォルダが
    消えたときに置かれていないレジメンの患者が残る。DB に版のあるものだけを選べる。
    """
    with api_client(tmp_path, skills_dir=skills_dir) as client:
        login_doctor(client)
        _place(
            skills_dir,
            "regimen-folfiri-bv",
            render_regimen_skill(extra_form("folfiri_bv"), 1),
        )
        codes = [
            g["code"] for g in client.get("/api/doctor/regimens").json()["regimens"]
        ]
        r = client.post("/api/doctor/patients", json={"regimen": "FOLFIRI-BV"})
        with db_conn(client.app) as conn:
            assert db.list_patients(conn) == []
    assert codes == ["FOLFOX", "CAPOX"]
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}

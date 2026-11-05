"""D4 レジメンの薬の名前の候補（`GET /api/doctor/regimen-drug-names`）。

- 採用済みのレジメンの今の版の form の薬 → 固定の5つ（plan-d4-regimen.md §5）の順。重複は除く
- form の無い版（旧 D4 の一文で上げた版）・読めない form は飛ばす（500 にしない）
- 名前だけを返す（薬の量・経路は持たない）
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from api_helpers import api_client, db_conn, login_doctor
from fastapi.testclient import TestClient
from regimen_fixtures import extra_form

from tsutae import db
from tsutae.config import SKILLS_HOME
from tsutae.db import repo_regimen_drafts as repo
from tsutae.regimen import RegimenForm, render_regimen_skill
from tsutae.regimen.drug_names import PLAN_DRUG_NAMES, merge_drug_names
from tsutae.regimen.source import canonical_form_json

URL = "/api/doctor/regimen-drug-names"
FOLFOX_NAMES = [
    "オキサリプラチン",
    "レボホリナート",
    "フルオロウラシル（急速静注）",
    "フルオロウラシル（46時間）",
]
FIXED_NAMES = [
    "パクリタキセル",
    "ラムシルマブ",
    "ベバシズマブ",
    "イリノテカン",
    "トリフルリジン・チピラシル",
]


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    return home / ".claude" / "skills"


@pytest.fixture
def client(tmp_path: Path, skills_dir: Path, fixed_today: str) -> Iterator[TestClient]:
    with api_client(tmp_path, skills_dir=skills_dir) as c:
        login_doctor(c)
        yield c


def _coded_form(code: str) -> RegimenForm:
    """FOLFIRI＋BV のフォームの識別名だけを替えたもの。"""
    form = extra_form("folfiri_bv")
    basic = form.basic.model_copy(update={"code": code})
    return form.model_copy(update={"basic": basic})


def _adopted(client: TestClient, skills_dir: Path, form_json: str | None) -> None:
    """版1を採用した形を置く（form_json が None なら form の無い版）。"""
    name = "regimen-adopted-test"
    text = render_regimen_skill(_coded_form("ADOPTED-TEST"), 1)
    (skills_dir / name).mkdir()
    (skills_dir / name / "SKILL.md").write_text(text, encoding="utf-8")
    with db_conn(client.app) as conn, db.write_transaction(conn):
        db.insert_skill_version_row(conn, name, 1, text, None)
        if form_json is not None:
            repo.insert_regimen_form_row(conn, name, 1, form_json)


def _names(client: TestClient) -> list[str]:
    r = client.get(URL)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"names"}
    return r.json()["names"]


def test_requires_doctor_cookie(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path) as c:
        r = c.get(URL)
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


def test_builtin_then_fixed_names_in_order(client: TestClient) -> None:
    names = _names(client)
    assert names[:4] == FOLFOX_NAMES
    assert "カペシタビン" in names
    assert names[-5:] == FIXED_NAMES
    assert len(names) == len(set(names))


def test_adopted_form_adds_names_and_drops_duplicates(
    client: TestClient, skills_dir: Path
) -> None:
    before = _names(client)
    assert "ベバシズマブ" in before
    assert "イリノテカン" in before
    _adopted(client, skills_dir, canonical_form_json(extra_form("folfiri_bv")))
    after = _names(client)
    assert after[:4] == FOLFOX_NAMES
    # 採用した版の薬は固定の5つより前に移り、同じ名前は1回だけ
    assert after.index("ベバシズマブ") < after.index("パクリタキセル")
    assert after.index("イリノテカン") < after.index("パクリタキセル")
    assert after.count("ベバシズマブ") == 1
    assert after[-3:] == [
        "パクリタキセル",
        "ラムシルマブ",
        "トリフルリジン・チピラシル",
    ]


def test_version_without_form_is_skipped(client: TestClient, skills_dir: Path) -> None:
    before = _names(client)
    _adopted(client, skills_dir, None)
    assert _names(client) == before


def test_broken_form_is_skipped_with_a_warning(
    client: TestClient, skills_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    before = _names(client)
    _adopted(client, skills_dir, '{"secret_marker": 1}')
    with caplog.at_level(logging.WARNING, logger="tsutae.regimen.drug_names"):
        assert _names(client) == before
    assert "regimen-adopted-test" in caplog.text
    assert "secret_marker" not in caplog.text


def test_folder_without_registered_version_is_not_adopted(
    tmp_path: Path, skills_dir: Path, fixed_today: str
) -> None:
    """起動の後に置いただけ（skill_versions に版が無い）のレジメンは採用済みではない。"""
    with api_client(tmp_path, skills_dir=skills_dir) as c:
        login_doctor(c)
        before = _names(c)
        name = "regimen-placed-test"
        (skills_dir / name).mkdir()
        (skills_dir / name / "SKILL.md").write_text(
            render_regimen_skill(_coded_form("PLACED-TEST"), 1), encoding="utf-8"
        )
        assert _names(c) == before


def test_merge_keeps_first_seen_order_and_trims() -> None:
    assert merge_drug_names([" A ", "B", None, "", "   ", "A"], ("B", "C")) == [
        "A",
        "B",
        "C",
    ]


def test_fixed_names_have_no_doses() -> None:
    assert list(PLAN_DRUG_NAMES) == FIXED_NAMES
    assert not any(ch.isdigit() for name in PLAN_DRUG_NAMES for ch in name)

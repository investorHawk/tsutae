"""医師 API: D4 レジメンの下書き・確認・採用（`/api/doctor/regimen-drafts`。spec 9.1・16）。

- 医師 Cookie が無ければ 401。GET 以外は別サイトからなら 403、本文つきは JSON でなければ 415
- 新規 → 直接編集 → 確認 → 採用 で、load_regimen_skill と GET /skills に新しいレジメンが出る
- token が古い・確かめが無い・患者のいるレジメンで日程を変えた なら 409。検査は 422（issues）
- working の間の PATCH・preview・adopt・discard は 409 working
- skills_home はテスト用の一時ディレクトリ
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from api_helpers import add_patient, api_client, db_conn, login_doctor
from fastapi.testclient import TestClient
from regimen_fixtures import extra_form, fill_patch

from tsutae import db
from tsutae.config import SKILLS_HOME
from tsutae.db import repo_regimen_drafts as repo
from tsutae.regimen.form import load_form_json
from tsutae.skills import load_regimen_skill

BASE = "/api/doctor/regimen-drafts"
CROSS = {"Sec-Fetch-Site": "cross-site"}


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


def _patch_body(patch: Any) -> dict[str, Any]:
    return {
        "changes": [asdict(c) for c in patch.changes],
        "adds": [asdict(a) for a in patch.adds],
        "deletes": list(patch.deletes),
    }


def _new(client: TestClient) -> dict[str, Any]:
    r = client.post(BASE, json={"from": "new"})
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    return r.json()["draft"]


def _filled(client: TestClient, name: str = "folfiri_bv") -> dict[str, Any]:
    draft = _new(client)
    form = load_form_json(_form_json(client, draft["id"]))
    body = _patch_body(fill_patch(form, extra_form(name)))
    r = client.patch(f"{BASE}/{draft['id']}/fields", json=body)
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _form_json(client: TestClient, draft_id: int) -> str:
    with db_conn(client.app) as conn:
        return repo.get_draft(conn, draft_id)["form_json"]


def _token(client: TestClient, draft_id: int) -> str:
    r = client.get(f"{BASE}/{draft_id}/preview")
    assert r.status_code == 200, r.text
    return r.json()["confirm_token"]


def _adopt(client: TestClient, draft_id: int, token: str, confirmed: bool = True):
    return client.post(
        f"{BASE}/{draft_id}/adopt",
        json={"confirm_token": token, "ai_values_confirmed": confirmed},
    )


def _set_standard(client: TestClient, draft_id: int, field_id: str) -> None:
    with db_conn(client.app) as conn:
        draft = repo.get_draft(conn, draft_id)
        repo.update_draft_form(
            conn,
            draft_id,
            form_json=draft["form_json"],
            sources_json=f'{{"{field_id}":"standard"}}',
            regimen=draft["regimen"],
        )


# --- 認証・CSRF・本文 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", BASE),
        ("post", BASE),
        ("get", f"{BASE}/1"),
        ("patch", f"{BASE}/1/fields"),
        ("post", f"{BASE}/1/discard"),
        ("get", f"{BASE}/1/preview"),
        ("post", f"{BASE}/1/adopt"),
        ("get", "/api/doctor/regimen-drug-names"),
    ],
)
def test_requires_doctor_cookie(tmp_path: Path, method: str, path: str) -> None:
    with api_client(tmp_path) as c:
        r = getattr(c, method)(path)
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", BASE, {"from": "new"}),
        ("patch", f"{BASE}/1/fields", {"changes": []}),
        ("post", f"{BASE}/1/discard", None),
        (
            "post",
            f"{BASE}/1/adopt",
            {"confirm_token": "x", "ai_values_confirmed": True},
        ),
    ],
)
def test_cross_site_is_refused(
    client: TestClient, method: str, path: str, body: Any
) -> None:
    r = client.request(method.upper(), path, json=body, headers=CROSS)
    assert r.status_code == 403
    assert r.json() == {"error": "cross_origin"}


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", BASE), ("PATCH", f"{BASE}/1/fields"), ("POST", f"{BASE}/1/adopt")],
)
def test_json_body_is_required(client: TestClient, method: str, path: str) -> None:
    r = client.request(
        method, path, content="from=new", headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 415


@pytest.mark.parametrize(
    "body",
    [{}, {"from": "new", "skill": "regimen-folfox"}, {"from": "old"}, {"x": 1}],
)
def test_create_needs_exactly_one_origin(client: TestClient, body: Any) -> None:
    r = client.post(BASE, json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


# --- 作る・読む ------------------------------------------------------------------------


def test_new_draft(client: TestClient) -> None:
    draft = _new(client)
    assert draft["status"] == "open" and draft["regimen"] is None
    assert draft["base_version"] is None and draft["version"] == 1
    assert draft["skill_name"] is None
    assert [q["key"] for q in draft["form"]["questions"]] == ["fever"]
    assert "prose" not in draft["form"]
    assert draft["sources"] == {} and draft["chat"] == []
    assert {"field_id": "basic.code", "code": "required", "message": "入力が要る"} in (
        draft["missing"]
    )
    assert draft["schedule_locked"] is False


def test_existing_draft_is_reused(client: TestClient) -> None:
    r = client.post(BASE, json={"skill": "regimen-folfox"})
    assert r.status_code == 200 and r.json()["created"] is True
    draft = r.json()["draft"]
    assert (draft["regimen"], draft["base_version"], draft["version"]) == (
        "FOLFOX",
        1,
        2,
    )
    assert draft["missing"] == []
    again = client.post(BASE, json={"skill": "regimen-folfox"}).json()
    assert again["created"] is False and again["draft"]["id"] == draft["id"]


@pytest.mark.parametrize(
    ("skill", "status", "code"),
    [
        ("regimen-nope", 404, "unknown_skill"),
        ("report-format-default", 400, "invalid_name"),
        ("../x", 400, "invalid_name"),
    ],
)
def test_existing_draft_errors(
    client: TestClient, skill: str, status: int, code: str
) -> None:
    r = client.post(BASE, json={"skill": skill})
    assert r.status_code == status and r.json() == {"error": code}


def test_list_and_get(client: TestClient) -> None:
    a = _new(client)
    b = client.post(BASE, json={"skill": "regimen-capox"}).json()["draft"]
    listed = client.get(BASE).json()["drafts"]
    assert [d["id"] for d in listed] == [a["id"], b["id"]]
    assert listed[1]["display_name"] == "CAPOX"
    assert client.get(f"{BASE}/{b['id']}").json()["draft"]["regimen"] == "CAPOX"
    r = client.get(f"{BASE}/999")
    assert r.status_code == 404 and r.json() == {"error": "not_found"}


def test_schedule_locked_flag(client: TestClient) -> None:
    add_patient(client.app, "FOLFOX")
    draft = client.post(BASE, json={"skill": "regimen-folfox"}).json()["draft"]
    assert draft["schedule_locked"] is True


# --- 直接編集 ---------------------------------------------------------------------------


def test_patch_fields(client: TestClient) -> None:
    draft = _filled(client)
    assert (
        draft["regimen"] == "FOLFIRI-BV" and draft["skill_name"] == "regimen-folfiri-bv"
    )
    assert draft["missing"] == []
    assert set(draft["sources"].values()) == {"doctor_edit"}


def test_patch_rejected_with_issues(client: TestClient) -> None:
    draft = _filled(client)
    before = _form_json(client, draft["id"])
    body = {
        "changes": [
            {"field_id": "drugs.d-bv.name", "value": "ベバシズマブ 5mg/kg"},
            {"field_id": "notes", "value": "連絡は 090-1234-5678"},
        ]
    }
    r = client.patch(f"{BASE}/{draft['id']}/fields", json=body)
    assert r.status_code == 422
    out = r.json()
    assert out["error"] == "invalid_fields"
    assert {(i["field_id"], i["code"]) for i in out["issues"]} == {
        ("drugs.d-bv.name", "dose"),
        ("notes", "identifier"),
    }
    assert "090" not in r.text
    assert _form_json(client, draft["id"]) == before


def test_patch_code_taken(client: TestClient) -> None:
    draft = _new(client)
    body = {"changes": [{"field_id": "basic.code", "value": "FOLFOX"}]}
    r = client.patch(f"{BASE}/{draft['id']}/fields", json=body)
    assert r.status_code == 422
    assert r.json()["issues"][0]["code"] == "code_taken"


def test_patch_bad_shape(client: TestClient) -> None:
    draft = _new(client)
    r = client.patch(f"{BASE}/{draft['id']}/fields", json={"changes": [{"x": 1}]})
    assert r.status_code == 422 and r.json() == {"error": "invalid_input"}


# --- working・破棄 ---------------------------------------------------------------------


def test_working_blocks_everything(client: TestClient) -> None:
    draft = _filled(client)
    token = _token(client, draft["id"])
    with db_conn(client.app) as conn:
        repo.begin_working(conn, draft["id"])
    calls = [
        client.patch(f"{BASE}/{draft['id']}/fields", json={"changes": []}),
        client.get(f"{BASE}/{draft['id']}/preview"),
        _adopt(client, draft["id"], token),
        client.post(f"{BASE}/{draft['id']}/discard"),
    ]
    for r in calls:
        assert r.status_code == 409 and r.json() == {"error": "working"}
    assert client.get(f"{BASE}/{draft['id']}").json()["draft"]["status"] == "working"


def test_discard(client: TestClient) -> None:
    draft = _filled(client)
    r = client.post(f"{BASE}/{draft['id']}/discard")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(BASE).json()["drafts"] == []
    r = client.post(f"{BASE}/{draft['id']}/discard")
    assert r.status_code == 409 and r.json() == {"error": "not_open"}
    assert client.get(f"{BASE}/{draft['id']}/preview").status_code == 409


# --- 確認・採用 ---------------------------------------------------------------------------


def test_preview_shape(client: TestClient) -> None:
    draft = _filled(client)
    _set_standard(client, draft["id"], "basic.target")
    body = client.get(f"{BASE}/{draft['id']}/preview").json()
    assert set(body) == {
        "draft_id",
        "skill_name",
        "base_version",
        "version",
        "ai_values",
        "skill_md",
        "patient_preview",
        "issues",
        "confirm_token",
    }
    assert body["ai_values"] == [
        {
            "field_id": "basic.target",
            "label": "対象",
            "value": "大腸がん",
            "source": "standard",
        }
    ]
    assert body["skill_md"]["kind"] == "full"
    assert body["skill_md"]["text"].startswith("---\nname: regimen-folfiri-bv\n")
    assert body["patient_preview"][-1] == {
        "key": "fever",
        "label": "体温",
        "text": "熱を測りましたか",
        "answer_type": "temperature",
    }


def test_adopt_new_regimen(client: TestClient, skills_dir: Path) -> None:
    draft = _filled(client)
    r = _adopt(client, draft["id"], _token(client, draft["id"]))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "ok": True,
        "skill_name": "regimen-folfiri-bv",
        "version": 1,
        "regimen": "FOLFIRI-BV",
    }
    assert load_regimen_skill("FOLFIRI-BV", skills_dir).version == 1
    skills = client.get("/api/doctor/skills").json()["skills"]
    assert {"name": "regimen-folfiri-bv", "version": 1} in skills
    keys = [
        q["key"] for q in client.get("/api/doctor/question-library").json()["questions"]
    ]
    assert "fatigue" in keys and "bleeding" in keys
    assert client.get(f"{BASE}/{draft['id']}").json()["draft"]["status"] == "adopted"
    r = _adopt(client, draft["id"], "x")
    assert r.status_code == 409 and r.json() == {"error": "not_open"}


def test_adopt_with_old_token(client: TestClient) -> None:
    draft = _filled(client)
    token = _token(client, draft["id"])
    body = {"changes": [{"field_id": "notes", "value": "あとから"}]}
    assert client.patch(f"{BASE}/{draft['id']}/fields", json=body).status_code == 200
    r = _adopt(client, draft["id"], token)
    assert r.status_code == 409 and r.json() == {"error": "token_mismatch"}


def test_adopt_without_confirmation(client: TestClient) -> None:
    draft = _filled(client)
    _set_standard(client, draft["id"], "basic.target")
    r = _adopt(client, draft["id"], _token(client, draft["id"]), confirmed=False)
    assert r.status_code == 409 and r.json() == {"error": "ai_values_unconfirmed"}


def test_adopt_schedule_locked(client: TestClient, skills_dir: Path) -> None:
    add_patient(client.app, "FOLFOX")
    draft = client.post(BASE, json={"skill": "regimen-folfox"}).json()["draft"]
    body = {"changes": [{"field_id": "basic.cycle_days", "value": 21}]}
    assert client.patch(f"{BASE}/{draft['id']}/fields", json=body).status_code == 200
    preview = client.get(f"{BASE}/{draft['id']}/preview").json()
    assert preview["skill_md"] is None
    assert [i["code"] for i in preview["issues"]] == ["schedule_locked"]
    r = _adopt(client, draft["id"], preview["confirm_token"])
    assert r.status_code == 409
    assert r.json()["error"] == "schedule_locked"
    assert r.json()["issues"][0]["field_id"] == "basic.cycle_days"
    assert load_regimen_skill("FOLFOX", skills_dir).version == 1


def test_adopt_existing_version_2(client: TestClient, skills_dir: Path) -> None:
    add_patient(client.app, "CAPOX")
    draft = client.post(BASE, json={"skill": "regimen-capox"}).json()["draft"]
    body = {"changes": [{"field_id": "notes", "value": "内服の期間は人ごとに違う"}]}
    assert client.patch(f"{BASE}/{draft['id']}/fields", json=body).status_code == 200
    diff = client.get(f"{BASE}/{draft['id']}/preview").json()["skill_md"]
    assert diff["kind"] == "diff" and "+内服の期間は人ごとに違う\n" in diff["text"]
    r = _adopt(client, draft["id"], _token(client, draft["id"]))
    assert r.status_code == 200 and r.json()["version"] == 2
    assert load_regimen_skill("CAPOX", skills_dir).version == 2
    with db_conn(client.app) as conn:
        assert db.get_skill_version(conn, "regimen-capox", 1) is not None


def test_adopt_incomplete_is_422(client: TestClient) -> None:
    draft = _new(client)
    r = _adopt(client, draft["id"], _token(client, draft["id"]))
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_form" and r.json()["issues"]


def test_adopt_bad_body(client: TestClient) -> None:
    draft = _filled(client)
    r = client.post(
        f"{BASE}/{draft['id']}/adopt",
        json={"confirm_token": "x", "ai_values_confirmed": "yes"},
    )
    assert r.status_code == 422 and r.json() == {"error": "invalid_input"}

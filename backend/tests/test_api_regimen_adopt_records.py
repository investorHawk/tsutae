"""D4 レジメンの採用の後の患者側（plan §3 T93「既存の記録は当時の版で表示される」）。

- FOLFOX の版2（だるさの質問を足した）を採用すると、患者の質問は版2・だるさつき
- 版1で付けた記録は版1の文、版2の記録は版2の文で出る。起動し直しても版1・版2が残る
- 確認の印に ASCII 以外の文字を送っても 409 token_mismatch（500 にしない）
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from api_helpers import add_patient, api_client, db_conn, login_doctor, register
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.config import SKILLS_HOME

BASE = "/api/doctor/regimen-drafts"
FATIGUE = {
    "key": "fatigue",
    "label": "だるさ",
    "text": "だるさや疲れやすさはありましたか",
    "answer_type": "three_level",
}
V1_KEYS = ("numbness", "diarrhea", "stomatitis", "nausea_appetite")


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    return home / ".claude" / "skills"


def _answers(*keys: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"question_key": k, "value": "none"} for k in keys]
    return [*out, {"question_key": "fever", "value": "not_measured"}]


def _post_entry(client: TestClient, pid: str, *keys: str) -> None:
    r = client.post(f"/api/patient/{pid}/entries", json={"answers": _answers(*keys)})
    assert r.status_code == 200, r.text


def _adopt_folfox_with_fatigue(client: TestClient) -> None:
    r = client.post(BASE, json={"skill": "regimen-folfox"})
    assert r.status_code == 200, r.text
    draft_id = r.json()["draft"]["id"]
    body = {
        "adds": [{"section": "questions", "row_id": "q-fatigue"}],
        "changes": [
            {"field_id": f"questions.q-fatigue.{name}", "value": value}
            for name, value in FATIGUE.items()
        ],
    }
    r = client.patch(f"{BASE}/{draft_id}/fields", json=body)
    assert r.status_code == 200, r.text
    preview = client.get(f"{BASE}/{draft_id}/preview").json()
    assert preview["issues"] == []
    r = client.post(
        f"{BASE}/{draft_id}/adopt",
        json={"confirm_token": preview["confirm_token"], "ai_values_confirmed": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2


def _entries(client: TestClient, pid: str) -> list[dict[str, Any]]:
    r = client.get(f"/api/patient/{pid}/entries")
    assert r.status_code == 200, r.text
    return r.json()["entries"]


def _texts(entry: dict[str, Any]) -> dict[str, str | None]:
    return {a["question_key"]: a["question_text"] for a in entry["answers"]}


def test_old_records_keep_the_version_they_were_made_with(
    tmp_path: Path, skills_dir: Path, fixed_today: str
) -> None:
    with api_client(tmp_path, skills_dir=skills_dir) as client:
        pid = add_patient(client.app, "FOLFOX")
        assert register(client, pid).status_code == 200
        before = client.get(f"/api/patient/{pid}/questions").json()
        assert before["skill_version"] == "regimen-folfox@1"
        _post_entry(client, pid, *V1_KEYS)

        login_doctor(client)
        _adopt_folfox_with_fatigue(client)

        after = client.get(f"/api/patient/{pid}/questions").json()
        assert after["skill_version"] == "regimen-folfox@2"
        assert FATIGUE["key"] in [q["key"] for q in after["questions"]]
        _post_entry(client, pid, *V1_KEYS, "fatigue")
        old, new = _entries(client, pid)
        assert old["skill_version"] == "regimen-folfox@1"
        assert new["skill_version"] == "regimen-folfox@2"
        assert all(t is not None for t in _texts(old).values())
        assert all(t is not None for t in _texts(new).values())
        assert _texts(new)["fatigue"] == FATIGUE["text"]

    with api_client(tmp_path, skills_dir=skills_dir) as client:  # 起動し直す
        register(client, pid)
        old, new = _entries(client, pid)
        assert all(t is not None for t in _texts(old).values())
        assert _texts(new)["fatigue"] == FATIGUE["text"]
        with db_conn(client.app) as conn:
            assert db.get_skill_version(conn, "regimen-folfox", 1) is not None
            assert db.get_skill_version(conn, "regimen-folfox", 2) is not None


@pytest.mark.parametrize("token", ["あ", "印" * 64])
def test_non_ascii_token_is_409(
    tmp_path: Path, skills_dir: Path, fixed_today: str, token: str
) -> None:
    with api_client(tmp_path, skills_dir=skills_dir) as client:
        login_doctor(client)
        draft_id = client.post(BASE, json={"from": "new"}).json()["draft"]["id"]
        r = client.post(
            f"{BASE}/{draft_id}/adopt",
            json={"confirm_token": token, "ai_values_confirmed": True},
        )
        assert r.status_code == 409
        assert r.json() == {"error": "token_mismatch"}

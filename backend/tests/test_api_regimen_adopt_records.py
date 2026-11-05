"""D4 レジメンの採用の後の患者側（plan §3 T93「既存の記録は当時の版で表示される」）。

- FOLFOX の版2（だるさの質問を足した）を採用すると、患者の質問は版2・だるさつき
- 版1で付けた記録は版1の質問集、版2の記録は版2の質問集に照らして受付で受け取る
  （端末が質問の文の写しを持つ。サーバーは文を返さない）。起動し直しても版1・版2が残る
- 確認の印に ASCII 以外の文字を送っても 409 token_mismatch（500 にしない）
"""

from __future__ import annotations

import shutil
from datetime import date
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


def _device_entry(client: TestClient, pid: str, no: int, *keys: str) -> dict[str, Any]:
    """端末の記録（今の版と、サーバーが返した時刻）。受付で送る形。"""
    version = client.get(f"/api/patient/{pid}/questions").json()["skill_version"]
    mark = client.post(f"/api/patient/{pid}/record-marks").json()
    return {
        "client_entry_id": f"demo-{no}",
        "recorded_at": mark["recorded_at"],
        "record_date": mark["record_date"],
        "kind": "answers",
        "by_proxy": False,
        "skill_version": version,
        "answers": _answers(*keys),
        "free_text": None,
    }


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


def _send(client: TestClient, entries: list[dict[str, Any]]) -> Any:
    return client.post("/api/visit", json={"reception_no": "A-1", "entries": entries})


def test_old_records_keep_the_version_they_were_made_with(
    tmp_path: Path, skills_dir: Path, fixed_today: str
) -> None:
    with api_client(tmp_path, skills_dir=skills_dir) as client:
        pid = add_patient(client.app, "FOLFOX", courses=[(1, date(2026, 10, 27))])
        assert register(client, pid).status_code == 200
        before = client.get(f"/api/patient/{pid}/questions").json()
        assert before["skill_version"] == "regimen-folfox@1"
        old = _device_entry(client, pid, 1, *V1_KEYS)

        login_doctor(client)
        _adopt_folfox_with_fatigue(client)

        after = client.get(f"/api/patient/{pid}/questions").json()
        assert after["skill_version"] == "regimen-folfox@2"
        by_key = {q["key"]: q for q in after["questions"]}
        assert by_key[FATIGUE["key"]]["text"] == FATIGUE["text"]
        new = _device_entry(client, pid, 2, *V1_KEYS, "fatigue")
        # 版1の記録に版2にしか無い質問は入らない
        mixed = {**old, "answers": _answers(*V1_KEYS, "fatigue")}
        assert _send(client, [mixed]).status_code == 422
        assert _send(client, [old, new]).status_code == 200
        with db_conn(client.app) as conn:
            versions = [e.skill_version for e in db.list_entries(conn, pid)]
        assert versions == ["regimen-folfox@1", "regimen-folfox@2"]

    with api_client(tmp_path, skills_dir=skills_dir) as client:  # 起動し直す
        register(client, pid)
        with db_conn(client.app) as conn:
            assert db.get_skill_version(conn, "regimen-folfox", 1) is not None
            assert db.get_skill_version(conn, "regimen-folfox", 2) is not None
        # 同じ記録の送り直しは、起動し直した後でも二重にならない
        assert _send(client, [old, new]).status_code == 200
        with db_conn(client.app) as conn:
            assert len(db.list_entries(conn, pid)) == 2


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

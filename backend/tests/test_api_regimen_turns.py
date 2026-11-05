"""医師 API: D4 レジメンの Claude の1往復（`POST /api/doctor/regimen-drafts/{id}/turns`）。

- 医師 Cookie・同じ origin・JSON の本文が要る。本文は {text}（1〜1000 字）
- 応答は {draft, turn_error}。成功は turn_error=null、時間切れ・失敗は open に戻して
  turn_error にコード（会話に失敗の行）
- 入力・依頼文の H1 は 422 h1_blocked（Claude を呼ばず保存もしない）。working の間は 409
- app.state.regimen_chat を偽物にする（ScriptChat・SdkRegimenChat＋偽の query）
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import api_client, db_conn, login_doctor
from fastapi.testclient import TestClient
from regimen_chat_fakes import ScriptChat, SlowChat, ToolQuery, change

from tsutae.config import SKILLS_HOME
from tsutae.db import repo_regimen_drafts as repo
from tsutae.regimen.chat_sdk import SdkRegimenChat

BASE = "/api/doctor/regimen-drafts"
CROSS = {"Sec-Fetch-Site": "cross-site"}
TEXT = "FOLFIRI＋BV。1コースは14日"


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


def _new(client: TestClient) -> dict[str, Any]:
    r = client.post(BASE, json={"from": "new"})
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _turn(client: TestClient, draft_id: int, text: str = TEXT, **kw: Any) -> Any:
    return client.post(f"{BASE}/{draft_id}/turns", json={"text": text}, **kw)


def test_turn_fills_fields_and_returns_the_draft(client: TestClient) -> None:
    chat = ScriptChat(
        [
            change("basic.cycle_days", 14),
            change("basic.target", "大腸がん", "standard"),
            (
                "ask",
                {
                    "field": "basic.display_name",
                    "question": "画面の名前はどうしますか",
                    "options": ["FOLFIRI＋BV", "FOLFIRI-BV"],
                },
            ),
        ]
    )
    client.app.state.regimen_chat = chat
    draft = _new(client)
    r = _turn(client, draft["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["turn_error"] is None
    got = body["draft"]
    assert got["status"] == "open" and got["generation"] == 1
    assert got["form"]["basic"]["cycle_days"] == 14
    assert got["sources"] == {
        "basic.cycle_days": "doctor_text",
        "basic.target": "standard",
    }
    doctor, assistant = got["chat"]
    assert doctor["role"] == "doctor" and doctor["text"] == TEXT
    assert assistant["changed"] == ["basic.cycle_days", "basic.target"]
    assert assistant["ask"] == {
        "field_id": "basic.display_name",
        "question": "画面の名前はどうしますか",
        "options": ["FOLFIRI＋BV", "FOLFIRI-BV"],
    }
    assert {"basic.cycle_days"} & {i["field_id"] for i in got["missing"]} == set()


def test_turn_through_sdk_chat_with_fake_query(
    client: TestClient, tmp_path: Path
) -> None:
    """SdkRegimenChat の組み立て（MCP サーバー・Hook）ごと通す。"""
    query = ToolQuery(
        [
            (
                "set_fields",
                {
                    "add_rows": ["drugs.1"],
                    "changes": [
                        {
                            "field": "drugs.1.name",
                            "value": "ベバシズマブ",
                            "source": "doctor_text",
                        },
                        {
                            "field": "drugs.1.route",
                            "value": "infusion",
                            "source": "standard",
                        },
                        {
                            "field": "drugs.1.days",
                            "value": [{"start": 1, "end": 1}],
                            "source": "doctor_text",
                        },
                    ],
                },
            ),
            (
                "propose_questions",
                # 症状がまだ無いので、先生が指定した質問として足す（standard は not_ready）
                {"from_library": ["diarrhea"], "source": "doctor_text"},
            ),
        ]
    )
    client.app.state.regimen_chat = SdkRegimenChat(
        client.app.state.settings, query_fn=query
    )
    draft = _new(client)
    r = _turn(client, draft["id"])
    assert r.status_code == 200, r.text
    got = r.json()["draft"]
    [drug] = got["form"]["drugs"]
    assert (drug["row_id"], drug["name"], drug["route"]) == (
        "drug1",
        "ベバシズマブ",
        "infusion",
    )
    assert got["sources"]["drugs.drug1.route"] == "standard"
    assert [q["key"] for q in got["form"]["questions"]] == ["fever", "diarrhea"]
    assert got["chat"][-1]["proposed"] == ["diarrhea"]
    assert got["chat"][-1]["text"] == "1コースを14日にした"
    prompt, options = query.seen[0]
    assert TEXT in prompt
    assert options.max_turns == client.app.state.settings.regimen_max_turns


@pytest.mark.parametrize(
    "text, rule",
    [
        ("受付 A-023 の件", "id_like"),
        ("磯鷲さんに合わせて", "unknown_before_honorific"),
        ("点滴は Day 1, 8, 15, 22、28日周期", "long_digits"),
    ],
)
def test_h1_is_422_and_nothing_is_saved(
    client: TestClient, text: str, rule: str
) -> None:
    """422 の本文は掛かった場所（text）と規則の名前だけ（文面は返さない）。"""
    chat = ScriptChat([change("basic.cycle_days", 14)])
    client.app.state.regimen_chat = chat
    draft = _new(client)
    r = _turn(client, draft["id"], text)
    assert r.status_code == 422
    assert r.json() == {
        "error": "h1_blocked",
        "issues": [
            {
                "field_id": "text",
                "code": "identifier",
                "message": f"個人を特定しうる表現の疑い（{rule}）",
            }
        ],
    }
    assert chat.seen == []
    got = client.get(f"{BASE}/{draft['id']}").json()["draft"]
    assert got["generation"] == 0 and got["chat"] == []


def test_h1_on_the_rest_of_the_prompt_says_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """先生の文でなく依頼文の他の部分で掛かれば field_id は prompt。"""
    from tsutae.regimen import chat_turn

    monkeypatch.setattr(
        chat_turn, "build_turn_prompt", lambda draft, text: f"{text}\nP-DEMO0001"
    )
    client.app.state.regimen_chat = ScriptChat()
    draft = _new(client)
    r = _turn(client, draft["id"])
    assert r.status_code == 422
    [issue] = r.json()["issues"]
    assert (issue["field_id"], issue["code"]) == ("prompt", "identifier")
    assert "P-DEMO0001" not in r.text


def test_working_is_409(client: TestClient) -> None:
    draft = _new(client)
    with db_conn(client.app) as conn:
        repo.begin_working(conn, draft["id"])
    r = _turn(client, draft["id"])
    assert r.status_code == 409 and r.json() == {"error": "working"}


def test_timeout_returns_open_and_failed_row(
    tmp_path: Path, skills_dir: Path, fixed_today: str
) -> None:
    with api_client(
        tmp_path, skills_dir=skills_dir, regimen_turn_timeout_s=0.05
    ) as client:
        login_doctor(client)
        client.app.state.regimen_chat = SlowChat()
        draft = _new(client)
        r = _turn(client, draft["id"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["turn_error"] == "timeout"
        assert body["draft"]["status"] == "open"
        assert [row["role"] for row in body["draft"]["chat"]] == ["doctor", "system"]
        assert body["draft"]["chat"][-1]["reason"] == "timeout"
        # 失敗の後もすぐ次の往復を送れる
        client.app.state.regimen_chat = ScriptChat()
        assert _turn(client, draft["id"]).json()["turn_error"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 1001},
        {"text": 1},
        {"text": "a", "x": 1},
    ],
)
def test_invalid_body_is_422(client: TestClient, body: dict[str, Any]) -> None:
    client.app.state.regimen_chat = ScriptChat()
    draft = _new(client)
    r = client.post(f"{BASE}/{draft['id']}/turns", json=body)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_input"


def test_missing_and_closed_drafts(client: TestClient) -> None:
    client.app.state.regimen_chat = ScriptChat()
    assert _turn(client, 999).status_code == 404
    draft = _new(client)
    client.post(f"{BASE}/{draft['id']}/discard")
    r = _turn(client, draft["id"])
    assert r.status_code == 409 and r.json() == {"error": "not_open"}


def test_requires_doctor_same_origin_and_json(
    client: TestClient, tmp_path: Path
) -> None:
    client.app.state.regimen_chat = ScriptChat()
    draft = _new(client)
    path = f"{BASE}/{draft['id']}/turns"
    assert client.post(path, json={"text": TEXT}, headers=CROSS).status_code == 403
    r = client.post(path, content="text=x", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    client.cookies.clear()
    assert client.post(path, json={"text": TEXT}).status_code == 401


def test_logs_have_no_text(client: TestClient) -> None:
    client.app.state.regimen_chat = ScriptChat(
        [change("notes", "連絡は外来の看護師へ")], reply="補足の指示を入れました"
    )
    draft = _new(client)
    assert (
        _turn(client, draft["id"], "エルプラットの施設の決まりを書いて").status_code
        == 200
    )
    with db_conn(client.app) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM pipeline_logs WHERE run_kind = 'regimen_chat'"
            ).fetchall()
        ]
    assert {r["event"] for r in rows} >= {"h1_check", "turn_start", "turn_end"}
    text = repr(rows)
    for secret in ("エルプラット", "連絡は外来", "補足の指示を入れました"):
        assert secret not in text


def test_reads_do_not_recover_a_turn_within_the_grace(
    client: TestClient,
) -> None:
    """読み出しの回復は往復の上限＋余裕を過ぎてから（往復が自分で結果を書く前に戻さない）。"""
    draft = _new(client)
    with db_conn(client.app) as conn:
        repo.begin_working(conn, draft["id"])
        settings = client.app.state.settings
        stamp = repo.get_draft(conn, draft["id"])["working_since"]
        assert settings.regimen_recover_after_s > settings.regimen_turn_timeout_s
        # 往復の上限を少し過ぎた（余裕の内）
        from datetime import timedelta

        from tsutae.db.connection import dt_to_db

        conn.execute(
            "UPDATE regimen_drafts SET working_since = ? WHERE id = ?",
            (
                dt_to_db(
                    stamp - timedelta(seconds=settings.regimen_turn_timeout_s + 1)
                ),
                draft["id"],
            ),
        )
        conn.commit()
    assert client.get(f"{BASE}/{draft['id']}").json()["draft"]["status"] == "working"

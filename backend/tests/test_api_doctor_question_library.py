"""医師 API: 質問の部品集（`GET/POST/DELETE /api/doctor/question-library`。spec 9.1・16）。

- 医師 Cookie が無ければ 401。POST・DELETE は別サイトからなら 403、POST は JSON でなければ 415
- 起動時に初期の6問が入る（何度起動しても重複しない）
- 追加: key の重複（消した key も）は 409 key_taken、形・H1 は 422 `{error, field}`
- 削除は選択肢から外すだけ。初期の6問は 409 seed_question、版が使っている key は 409 in_use
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_helpers import api_client, db_conn, login_doctor
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.schemas import Question

URL = "/api/doctor/question-library"
SEED_KEYS = [
    "numbness",
    "diarrhea",
    "stomatitis",
    "nausea_appetite",
    "hand_foot",
    "fever",
]
NEW = {
    "key": "fatigue",
    "label": "だるさ",
    "text": "だるさや疲れやすさはありましたか",
    "answer_type": "three_level",
}
ITEM_KEYS = {"key", "label", "text", "answer_type", "origin"}


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        login_doctor(c)
        yield c


def _keys(client: TestClient) -> list[str]:
    r = client.get(URL)
    assert r.status_code == 200
    return [q["key"] for q in r.json()["questions"]]


# --- 認証・CSRF ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", URL), ("post", URL), ("delete", f"{URL}/fatigue")],
)
def test_requires_doctor_cookie(tmp_path: Path, method: str, path: str) -> None:
    with api_client(tmp_path) as c:
        r = c.request(method.upper(), path, json=NEW if method == "post" else None)
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


@pytest.mark.parametrize(
    "headers", [{"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://evil.example"}]
)
def test_post_and_delete_reject_cross_origin(
    client: TestClient, headers: dict[str, str]
) -> None:
    client.post(URL, json=NEW)
    r = client.post(URL, json={**NEW, "key": "bleeding"}, headers=headers)
    assert (r.status_code, r.json()) == (403, {"error": "cross_origin"})
    r = client.delete(f"{URL}/fatigue", headers=headers)
    assert (r.status_code, r.json()) == (403, {"error": "cross_origin"})
    assert "bleeding" not in _keys(client)
    assert "fatigue" in _keys(client)


def test_get_ignores_cross_site_header(client: TestClient) -> None:
    r = client.get(URL, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200


@pytest.mark.parametrize("content_type", [None, "text/plain"])
def test_post_requires_json_content_type(
    client: TestClient, content_type: str | None
) -> None:
    headers = {"Content-Type": content_type} if content_type else {}
    r = client.post(URL, content=json.dumps(NEW), headers=headers)
    assert (r.status_code, r.json()) == (415, {"error": "unsupported_media_type"})


# --- 一覧 --------------------------------------------------------------------------


def test_startup_seeds_six_questions(client: TestClient) -> None:
    r = client.get(URL)
    assert r.status_code == 200
    questions = r.json()["questions"]
    assert [q["key"] for q in questions] == SEED_KEYS
    assert all(set(q) == ITEM_KEYS for q in questions)
    assert all(q["origin"] == "seed" for q in questions)
    fever = questions[-1]
    assert fever == {
        "key": "fever",
        "label": "体温",
        "text": "熱を測りましたか",
        "answer_type": "temperature",
        "origin": "seed",
    }


def test_restart_does_not_duplicate_seed(tmp_path: Path) -> None:
    with api_client(tmp_path) as c:
        login_doctor(c)
        assert c.post(URL, json=NEW).status_code == 200
    with api_client(tmp_path) as c:
        login_doctor(c)
        assert _keys(c) == [*SEED_KEYS, "fatigue"]
        with db_conn(c.app) as conn:
            count = conn.execute("SELECT COUNT(*) FROM question_library").fetchone()
        assert count[0] == 7


# --- 追加 ------------------------------------------------------------------------


def test_post_adds_question(client: TestClient) -> None:
    r = client.post(URL, json=NEW)
    assert r.status_code == 200
    assert r.json() == {"question": {**NEW, "origin": "doctor"}}
    assert _keys(client) == [*SEED_KEYS, "fatigue"]


def test_post_defaults_to_three_level(client: TestClient) -> None:
    body = {k: v for k, v in NEW.items() if k != "answer_type"}
    r = client.post(URL, json=body)
    assert r.status_code == 200
    assert r.json()["question"]["answer_type"] == "three_level"


@pytest.mark.parametrize("key", ["fatigue", "diarrhea", "fever"])
def test_post_rejects_duplicate_key(client: TestClient, key: str) -> None:
    client.post(URL, json=NEW)
    r = client.post(URL, json={**NEW, "key": key, "label": "べつ"})
    assert (r.status_code, r.json()) == (409, {"error": "key_taken"})


def test_hidden_key_cannot_be_posted_again(client: TestClient) -> None:
    client.post(URL, json=NEW)
    assert client.delete(f"{URL}/fatigue").status_code == 200
    r = client.post(URL, json=NEW)
    assert (r.status_code, r.json()) == (409, {"error": "key_taken"})
    assert "fatigue" not in _keys(client)


@pytest.mark.parametrize(
    ("override", "error", "field"),
    [
        ({"key": "Fatigue"}, "invalid_key", "key"),
        ({"key": "fa-tigue"}, "invalid_key", "key"),
        ({"key": "temperature"}, "reserved_key", "key"),
        ({"key": "q_meal2"}, "h1_blocked", "key"),
        ({"label": ""}, "invalid_label", "label"),
        ({"label": "だる|さ"}, "invalid_label", "label"),
        ({"label": "磯鷲さん"}, "h1_blocked", "label"),
        ({"text": "だるさは\nありましたか"}, "invalid_text", "text"),
        ({"label": "あ" * 21}, "invalid_label", "label"),
        ({"text": "あ" * 201}, "invalid_text", "text"),
        ({"text": "1日2g飲みましたか"}, "invalid_text", "text"),
        ({"text": "質問: だるさはありましたか"}, "invalid_text", "text"),
        ({"text": "だるさ, 疲れはありましたか"}, "invalid_text", "text"),
        ({"text": "だるさ #ありましたか"}, "invalid_text", "text"),
        ({"text": "null"}, "invalid_text", "text"),
        ({"text": "磯鷲さんにもらった薬は飲みましたか"}, "h1_blocked", "text"),
        ({"answer_type": "temperature"}, "invalid_answer_type", "answer_type"),
    ],
)
def test_post_rejects_bad_values_with_field(
    client: TestClient, override: dict[str, str], error: str, field: str
) -> None:
    r = client.post(URL, json={**NEW, **override})
    assert r.status_code == 422
    assert r.json() == {"error": error, "field": field}
    assert _keys(client) == SEED_KEYS


@pytest.mark.parametrize(
    "body",
    [
        {**NEW, "origin": "seed"},
        {**NEW, "hidden": True},
        {"key": "fatigue", "label": "だるさ"},
        {**NEW, "key": 1},
        {**NEW, "text": "あ" * 5000},
        [],
    ],
)
def test_post_rejects_bad_shape(client: TestClient, body: object) -> None:
    r = client.post(URL, json=body)
    assert (r.status_code, r.json()) == (422, {"error": "invalid_input"})
    assert _keys(client) == SEED_KEYS


# --- 削除 ------------------------------------------------------------------------


def test_delete_hides_question(client: TestClient) -> None:
    client.post(URL, json=NEW)
    r = client.delete(f"{URL}/fatigue")
    assert (r.status_code, r.json()) == (200, {"ok": True})
    assert _keys(client) == SEED_KEYS
    with db_conn(client.app) as conn:
        row = db.get_library_question(conn, "fatigue")
    assert row is not None and row["hidden"] is True
    assert client.delete(f"{URL}/fatigue").status_code == 200  # 何度でも


@pytest.mark.parametrize("key", SEED_KEYS)
def test_delete_seed_is_409(client: TestClient, key: str) -> None:
    r = client.delete(f"{URL}/{key}")
    assert (r.status_code, r.json()) == (409, {"error": "seed_question"})
    assert key in _keys(client)


def test_delete_key_used_by_version_is_409(client: TestClient) -> None:
    client.post(URL, json=NEW)
    with db_conn(client.app) as conn:
        db.save_skill_version(
            conn,
            "regimen-ram-wptx",
            1,
            "---\n",
            [
                Question(key="fatigue", text=NEW["text"], answer_type="three_level"),
                Question(
                    key="fever", text="熱を測りましたか", answer_type="temperature"
                ),
            ],
        )
    r = client.delete(f"{URL}/fatigue")
    assert (r.status_code, r.json()) == (409, {"error": "in_use"})
    assert "fatigue" in _keys(client)


def test_delete_unknown_is_404(client: TestClient) -> None:
    r = client.delete(f"{URL}/fatigue")
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})


@pytest.mark.parametrize("key", ["Fatigue", "fa-tigue", "a", "a" * 42])
def test_delete_bad_key_shape_is_422(client: TestClient, key: str) -> None:
    r = client.delete(f"{URL}/{key}")
    assert (r.status_code, r.json()) == (422, {"error": "invalid_input"})

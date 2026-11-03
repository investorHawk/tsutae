"""医師 API の本文つきの POST は Content-Type: application/json だけを受ける（415）。

CSRF の追加の守り: フォーム（application/x-www-form-urlencoded・multipart/form-data・
text/plain）は CORS の preflight なしに別サイトから送れる。本文の無い POST
（printed・approve・reject）は frontend が Content-Type を付けないので対象外。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_helpers import api_client, login_doctor
from fastapi.testclient import TestClient

from tsutae.api.deps import is_json_media_type

BODY_POSTS: list[tuple[str, dict]] = [
    ("/api/doctor/patients", {"regimen": "FOLFOX"}),
    (
        "/api/doctor/courses",
        {"patient_id": "P-AAAAAAAA", "course_no": 1, "infusion_date": "2026-10-01"},
    ),
    (
        "/api/doctor/skill-changes",
        {"skill_name": "regimen-folfox", "request_text": "下痢の質問を直して"},
    ),
]
BAD_TYPES = [
    "text/plain",
    "text/plain;charset=UTF-8",
    "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=x",
    "application/jsonx",
    "",
]


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def doctor(client: TestClient) -> TestClient:
    login_doctor(client)
    return client


def _post(client: TestClient, path: str, body: dict, content_type: str | None):
    headers = {} if content_type is None else {"Content-Type": content_type}
    return client.post(
        path, content=json.dumps(body, ensure_ascii=False).encode(), headers=headers
    )


@pytest.mark.parametrize(("path", "body"), BODY_POSTS)
@pytest.mark.parametrize("content_type", BAD_TYPES)
def test_non_json_body_post_is_415(
    doctor: TestClient, path: str, body: dict, content_type: str
) -> None:
    res = _post(doctor, path, body, content_type)
    assert res.status_code == 415
    assert res.json() == {"error": "unsupported_media_type"}


@pytest.mark.parametrize(("path", "body"), BODY_POSTS)
def test_missing_content_type_is_415(doctor: TestClient, path: str, body: dict) -> None:
    res = _post(doctor, path, body, None)
    assert res.status_code == 415


@pytest.mark.parametrize(("path", "body"), BODY_POSTS)
@pytest.mark.parametrize(
    "content_type", ["application/json", "application/json; charset=utf-8"]
)
def test_json_body_post_is_not_415(
    doctor: TestClient, path: str, body: dict, content_type: str
) -> None:
    res = _post(doctor, path, body, content_type)
    assert res.status_code != 415


def test_json_post_still_works(doctor: TestClient) -> None:
    res = doctor.post("/api/doctor/patients", json={"regimen": "FOLFOX"})
    assert res.status_code == 200 and res.json()["id"].startswith("P-")


@pytest.mark.parametrize(("path", "body"), BODY_POSTS)
def test_cookie_is_checked_before_media_type(
    client: TestClient, path: str, body: dict
) -> None:
    res = _post(client, path, body, "text/plain")
    assert res.status_code == 401
    assert res.json() == {"error": "not_logged_in"}


def test_media_type_is_checked_before_body_validation(doctor: TestClient) -> None:
    res = doctor.post(
        "/api/doctor/patients",
        content=b"regimen=FOLFOX",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 415


@pytest.mark.parametrize(
    "path",
    [
        "/api/doctor/visits/1/printed",
        "/api/doctor/skill-changes/1/approve",
        "/api/doctor/skill-changes/1/reject",
    ],
)
def test_bodyless_posts_are_not_checked(doctor: TestClient, path: str) -> None:
    # frontend の http.ts は本文の無い POST に Content-Type を付けない
    assert doctor.post(path).status_code != 415


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("application/json", True),
        ("Application/JSON", True),
        ("application/json; charset=utf-8", True),
        (" application/json ;charset=UTF-8", True),
        ("application/jsonx", False),
        ("application/problem+json", False),
        ("text/plain", False),
        ("", False),
        (None, False),
    ],
)
def test_is_json_media_type(value: str | None, expected: bool) -> None:
    assert is_json_media_type(value) is expected

"""医師 API: ログイン・Cookie の検査・患者・コース（docs/architecture.md §8 医師・§8b）。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from api_helpers import (
    TEST_PASSWORD,
    TEST_SECRET,
    add_patient,
    api_client,
    db_conn,
    login_doctor,
)
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.api.deps import DOCTOR_COOKIE, make_doctor_token
from tsutae.config import now

C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]

# 医師 Cookie が要る全経路（ログイン・ログアウトを除く）
PROTECTED: list[tuple[str, str, dict | None]] = [
    ("get", "/api/doctor/patients", None),
    ("post", "/api/doctor/patients", {"regimen": "FOLFOX"}),
    ("get", "/api/doctor/patients/P-AAAAAAAA/courses", None),
    ("get", "/api/doctor/patients/P-AAAAAAAA/visits", None),
    ("get", "/api/doctor/patients/P-AAAAAAAA/entries", None),
    (
        "post",
        "/api/doctor/courses",
        {"patient_id": "P-AAAAAAAA", "course_no": 1, "infusion_date": "2026-10-01"},
    ),
    ("get", "/api/doctor/visits", None),
    ("get", "/api/doctor/visits/1/report", None),
    ("post", "/api/doctor/visits/1/printed", None),
    ("get", "/api/doctor/visits/1/unprocessed", None),
    ("get", "/api/doctor/pipeline/1/events", None),
    ("get", "/api/doctor/skills", None),
    ("get", "/api/doctor/skills/regimen-folfox", None),
    (
        "post",
        "/api/doctor/skill-changes",
        {"skill_name": "regimen-folfox", "request_text": "下痢の質問を直して"},
    ),
    ("get", "/api/doctor/skill-changes", None),
    ("post", "/api/doctor/skill-changes/1/approve", None),
    ("post", "/api/doctor/skill-changes/1/reject", None),
]


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def doctor(client: TestClient) -> TestClient:
    login_doctor(client)
    return client


def _call(client: TestClient, method: str, path: str, body: dict | None):
    if method == "get":
        return client.get(path)
    return client.post(path, json=body) if body is not None else client.post(path)


# ---------------------------------------------------------------------------
# ログイン・ログアウト
# ---------------------------------------------------------------------------


def test_routers_are_mounted(client: TestClient) -> None:
    assert client.app.state.optional_routers == (
        "tsutae.api.doctor",
        "tsutae.api.doctor_skills",
    )


def test_login_sets_signed_httponly_cookie(client: TestClient) -> None:
    r = client.post("/api/doctor/login", json={"password": TEST_PASSWORD})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    header = r.headers["set-cookie"]
    assert header.startswith(f"{DOCTOR_COOKIE}=")
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert client.get("/api/doctor/patients").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"password": "wrong"},
        {"password": ""},
        {"password": TEST_PASSWORD + " "},
        {"password": TEST_PASSWORD.upper()},
    ],
)
def test_login_wrong_password_is_401(client: TestClient, body: dict) -> None:
    r = client.post("/api/doctor/login", json=body)
    assert r.status_code == 401
    assert r.json() == {"error": "bad_password"}
    assert DOCTOR_COOKIE not in r.cookies
    assert client.get("/api/doctor/patients").status_code == 401


@pytest.mark.parametrize(
    "body",
    [{}, {"password": 123}, {"password": "x" * 2000}, {"password": "a", "x": 1}],
)
def test_login_invalid_body_is_422(client: TestClient, body: dict) -> None:
    r = client.post("/api/doctor/login", json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


def test_logout_clears_cookie(client: TestClient) -> None:
    client.post("/api/doctor/login", json={"password": TEST_PASSWORD})
    assert client.get("/api/doctor/patients").status_code == 200
    r = client.post("/api/doctor/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    header = r.headers["set-cookie"]
    assert header.startswith(f"{DOCTOR_COOKIE}=") and "Max-Age=0" in header
    assert client.get("/api/doctor/patients").status_code == 401


def test_logout_without_cookie_is_ok(client: TestClient) -> None:
    """Cookie を消すだけなので、失効後でもログアウトできる（何も見せない）。"""
    r = client.post("/api/doctor/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------------------------------------------------------------------------
# 医師 Cookie の検査（無い・改ざん・期限切れ・別の鍵・患者 Cookie）
# ---------------------------------------------------------------------------


def _tampered() -> str:
    token = make_doctor_token(TEST_SECRET, now())
    issued, sig = token.split(".")
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    return f"{issued}.{flipped}"


BAD_TOKENS = {
    "tampered": _tampered,
    "expired": lambda: make_doctor_token(TEST_SECRET, now() - timedelta(hours=13)),
    "future": lambda: make_doctor_token(TEST_SECRET, now() + timedelta(hours=1)),
    "other_secret": lambda: make_doctor_token("other-secret", now()),
    "garbage": lambda: "not-a-token",
    "issued_changed": lambda: "1" + make_doctor_token(TEST_SECRET, now()),
}


@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_protected_without_cookie_is_401(
    client: TestClient, method: str, path: str, body: dict | None
) -> None:
    r = _call(client, method, path, body)
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


@pytest.mark.parametrize("kind", sorted(BAD_TOKENS))
@pytest.mark.parametrize("method, path, body", PROTECTED)
def test_protected_with_bad_cookie_is_401(
    client: TestClient, method: str, path: str, body: dict | None, kind: str
) -> None:
    client.cookies.set(DOCTOR_COOKIE, BAD_TOKENS[kind]())
    r = _call(client, method, path, body)
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


def test_patient_cookie_is_not_doctor(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    client.post("/api/patient/register", json={"pid": pid})
    assert client.get("/api/doctor/patients").status_code == 401


def test_auth_is_checked_before_body(client: TestClient) -> None:
    r = client.post("/api/doctor/courses", json={"broken": True})
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


def test_cookie_within_12_hours_is_valid(client: TestClient) -> None:
    token = make_doctor_token(TEST_SECRET, now() - timedelta(hours=11, minutes=59))
    client.cookies.set(DOCTOR_COOKIE, token)
    assert client.get("/api/doctor/patients").status_code == 200


# ---------------------------------------------------------------------------
# 患者
# ---------------------------------------------------------------------------


def test_create_patient_returns_register_url(doctor: TestClient) -> None:
    r = doctor.post("/api/doctor/patients", json={"regimen": "CAPOX"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "register_url"}
    assert body["register_url"] == f"http://testserver/register?pid={body['id']}"
    with db_conn(doctor.app) as conn:
        assert db.get_patient(conn, body["id"])["regimen"] == "CAPOX"


@pytest.mark.parametrize(
    "body", [{}, {"regimen": "XELOX"}, {"regimen": "folfox"}, {"regimen": 1}]
)
def test_create_patient_invalid_is_422(doctor: TestClient, body: dict) -> None:
    r = doctor.post("/api/doctor/patients", json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}
    with db_conn(doctor.app) as conn:
        assert db.list_patients(conn) == []


def test_list_patients(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path, public_base_url="https://tsutae.example/") as c:
        login_doctor(c)
        first = add_patient(c.app, "FOLFOX")
        second = add_patient(c.app, "CAPOX")
        r = c.get("/api/doctor/patients")
    assert r.status_code == 200
    patients = r.json()["patients"]
    assert [p["id"] for p in patients] == [first, second]
    assert patients[1]["regimen"] == "CAPOX"
    assert set(patients[0]) == {
        "id",
        "regimen",
        "created_at",
        "register_url",
        "last_record_date",
        "days_since_last_record",
        "record_stale",
        "current_course_no",
        "current_day",
        "next_visit",
    }
    assert patients[0]["register_url"] == (
        f"https://tsutae.example/register?pid={first}"
    )
    assert patients[0]["created_at"].endswith("+09:00")


# ---------------------------------------------------------------------------
# コース
# ---------------------------------------------------------------------------


def _course(pid: str, no: int, infusion: str, **extra: object) -> dict:
    return {"patient_id": pid, "course_no": no, "infusion_date": infusion, **extra}


def test_list_courses(doctor: TestClient) -> None:
    pid = add_patient(doctor.app, courses=C3)
    r = doctor.get(f"/api/doctor/patients/{pid}/courses")
    assert r.status_code == 200
    courses = r.json()["courses"]
    assert [c["course_no"] for c in courses] == [1, 2, 3]
    assert courses[2]["infusion_date"] == "2026-10-27"
    assert courses[0]["planned_date"] is None


@pytest.mark.parametrize("pid", ["P-ZZZZZZZZ", "p-aaaaaaaa", "nope"])
def test_list_courses_unknown_patient_is_404(doctor: TestClient, pid: str) -> None:
    r = doctor.get(f"/api/doctor/patients/{pid}/courses")
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_patient"}


def test_save_course_and_update(doctor: TestClient) -> None:
    pid = add_patient(doctor.app, courses=C3[:2])
    body = _course(pid, 3, "2026-10-27", planned_date="2026-10-25", note="延期", id=999)
    r = doctor.post("/api/doctor/courses", json=body)
    assert r.status_code == 200
    saved = r.json()
    assert saved["patient_id"] == pid and saved["course_no"] == 3
    assert saved["planned_date"] == "2026-10-25"
    assert saved["note"] == "延期"
    assert saved["id"] != 999  # 送られた id は使わない
    r = doctor.post("/api/doctor/courses", json=_course(pid, 3, "2026-10-28"))
    assert r.status_code == 200
    assert r.json()["id"] == saved["id"]
    with db_conn(doctor.app) as conn:
        courses = db.list_courses(conn, pid)
    assert [c.infusion_date for c in courses] == [
        date(2026, 9, 27),
        date(2026, 10, 13),
        date(2026, 10, 28),
    ]


@pytest.mark.parametrize(
    "course_no, infusion",
    [
        (3, "2026-10-13"),  # C2 と同じ日
        (3, "2026-10-01"),  # C2 より前
        (2, "2026-09-20"),  # C1 より前に置き換え
        (1, "2026-10-20"),  # C2 より後に置き換え
    ],
)
def test_save_course_contradiction_is_400(
    doctor: TestClient, course_no: int, infusion: str
) -> None:
    pid = add_patient(doctor.app, courses=C3[:2])
    r = doctor.post("/api/doctor/courses", json=_course(pid, course_no, infusion))
    assert r.status_code == 400
    assert r.json() == {"error": "course_order"}
    with db_conn(doctor.app) as conn:
        courses = db.list_courses(conn, pid)
    assert [c.infusion_date for c in courses] == [
        date(2026, 9, 27),
        date(2026, 10, 13),
    ]


def test_save_course_unknown_patient_is_404(doctor: TestClient) -> None:
    r = doctor.post("/api/doctor/courses", json=_course("P-ZZZZZZZZ", 1, "2026-10-01"))
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_patient"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"patient_id": "P-AAAAAAAA", "course_no": 0, "infusion_date": "2026-10-01"},
        {"patient_id": "P-AAAAAAAA", "course_no": 1, "infusion_date": "2026-13-01"},
        {"patient_id": "P-AAAAAAAA", "course_no": 1},
        {
            "patient_id": "P-AAAAAAAA",
            "course_no": 1,
            "infusion_date": "2026-10-01",
            "note": "x" * 201,
        },
        {
            "patient_id": "P-AAAAAAAA",
            "course_no": 1,
            "infusion_date": "2026-10-01",
            "unknown": 1,
        },
    ],
)
def test_save_course_invalid_is_422(doctor: TestClient, body: dict) -> None:
    add_patient(doctor.app, patient_id="P-AAAAAAAA")
    r = doctor.post("/api/doctor/courses", json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}

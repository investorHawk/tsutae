"""医師 API の CSRF の守り（`deps.require_same_origin`）。

状態を変える医師 API の POST（login を除く）は、Sec-Fetch-Site が cross-site・same-site
なら 403 cross_origin。Origin があり、要求の Host から作った origin とも
public_base_url の origin とも違えば 403。どちらのヘッダも無ければ通す。
患者 API には付けない。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from api_helpers import add_patient, api_client, login_doctor, register
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsutae.api import deps

LOGIN = "/api/doctor/login"
DOCTOR_PREFIX = "/api/doctor/"
CROSS = {"error": "cross_origin"}
C1 = [(1, date(2026, 10, 27))]


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        login_doctor(c)
        yield c


def _doctor_posts(app: FastAPI) -> list[str]:
    """create_app() に載った /api/doctor/* の POST（login を除く）。"""
    from fastapi.routing import iter_route_contexts

    found: set[str] = set()
    for route in iter_route_contexts(app.routes):
        path = route.path_format or route.path
        if not path or not path.startswith(DOCTOR_PREFIX) or path == LOGIN:
            continue
        if "POST" in (route.methods or set()):
            found.add(path)
    return sorted(found)


def _fill(path: str) -> str:
    return path.replace("{vid}", "1").replace("{change_id}", "1")


def test_doctor_posts_are_listed(client: TestClient) -> None:
    posts = _doctor_posts(client.app)
    assert "/api/doctor/logout" in posts
    assert "/api/doctor/visits/{vid}/printed" in posts
    assert "/api/doctor/skill-changes/{change_id}/approve" in posts
    assert "/api/doctor/skill-changes/{change_id}/reject" in posts
    assert "/api/doctor/patients" in posts
    assert "/api/doctor/courses" in posts
    assert "/api/doctor/skill-changes" in posts


@pytest.mark.parametrize("site", ["cross-site", "same-site", "Cross-Site"])
def test_every_doctor_post_rejects_cross_site_fetch(
    client: TestClient, site: str
) -> None:
    bad = []
    for path in _doctor_posts(client.app):
        login_doctor(client)
        r = client.post(_fill(path), headers={"Sec-Fetch-Site": site})
        if r.status_code != 403 or r.json() != CROSS:
            bad.append(f"{path} -> {r.status_code}")
    assert bad == []


def test_every_doctor_post_rejects_foreign_origin(client: TestClient) -> None:
    bad = []
    for path in _doctor_posts(client.app):
        login_doctor(client)
        r = client.post(_fill(path), headers={"Origin": "https://evil.example"})
        if r.status_code != 403 or r.json() != CROSS:
            bad.append(f"{path} -> {r.status_code}")
    assert bad == []


def test_null_origin_is_rejected(client: TestClient) -> None:
    r = client.post("/api/doctor/visits/1/printed", headers={"Origin": "null"})
    assert r.status_code == 403 and r.json() == CROSS


def test_cross_origin_with_json_body_is_403_before_validation(
    client: TestClient,
) -> None:
    r = client.post(
        "/api/doctor/patients",
        json={"regimen": "FOLFOX"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403 and r.json() == CROSS


def test_no_headers_pass(client: TestClient) -> None:
    """TestClient・curl・古いブラウザ（Sec-Fetch-Site も Origin も無い）。"""
    r = client.post("/api/doctor/patients", json={"regimen": "FOLFOX"})
    assert r.status_code == 200


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_same_origin_fetch_passes(client: TestClient, site: str) -> None:
    r = client.post(
        "/api/doctor/patients",
        json={"regimen": "FOLFOX"},
        headers={"Sec-Fetch-Site": site},
    )
    assert r.status_code == 200


def test_origin_matching_host_passes(client: TestClient) -> None:
    r = client.post(
        "/api/doctor/patients",
        json={"regimen": "FOLFOX"},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 200


def test_vite_dev_proxy_passes(tmp_path: Path, fixed_today: str) -> None:
    """開発の Vite proxy: Origin も Host も 127.0.0.1:5173 のまま届く。"""
    with api_client(tmp_path, public_base_url="http://localhost:5173") as c:
        login_doctor(c)
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "Host": "127.0.0.1:5173",
            "Sec-Fetch-Site": "same-origin",
        }
        r = c.post("/api/doctor/patients", json={"regimen": "FOLFOX"}, headers=headers)
        assert r.status_code == 200
        assert c.post("/api/doctor/logout", headers=headers).status_code == 200


def test_origin_matching_public_base_url_passes(
    tmp_path: Path, fixed_today: str
) -> None:
    """手前のプロキシが Host を書き換えても、公開の origin なら通す。"""
    with api_client(tmp_path, public_base_url="https://tsutae.example/") as c:
        login_doctor(c)
        r = c.post(
            "/api/doctor/patients",
            json={"regimen": "FOLFOX"},
            headers={"Origin": "https://tsutae.example", "Host": "127.0.0.1:8000"},
        )
        assert r.status_code == 200
        r = c.post(
            "/api/doctor/patients",
            json={"regimen": "FOLFOX"},
            headers={"Origin": "http://tsutae.example", "Host": "127.0.0.1:8000"},
        )
        assert r.status_code == 403 and r.json() == CROSS


def test_login_is_not_checked(client: TestClient) -> None:
    r = client.post(
        LOGIN,
        json={"password": "test-doctor-password"},
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    )
    assert r.status_code == 200


def test_get_is_not_checked(client: TestClient) -> None:
    r = client.get(
        "/api/doctor/visits",
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    )
    assert r.status_code == 200


def test_patient_api_is_not_checked(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C1)
    assert register(client, pid).status_code == 200
    headers = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}
    r = client.post(
        f"/api/patient/{pid}/entries", json={"too_sick": True}, headers=headers
    )
    assert r.status_code == 200
    r = client.post("/api/visit", json={"reception_no": "A-1"}, headers=headers)
    assert r.status_code == 200


def test_require_same_origin_is_exported() -> None:
    assert "require_same_origin" in deps.__all__

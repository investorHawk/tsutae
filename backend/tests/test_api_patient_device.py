"""スマホ保存の患者 API（plan-device-records §5.3〜§5.5・§5.9）。

- `GET /questions` の fixed_rules: 画面のコードで比べるための規則（体温はサーバーに送らない）
- `GET /{pid}/visit-window`: 送る範囲（前コースの Day1〜今日。無ければ今コースの Day1）
- `GET /{pid}/visit-days`: 受診日と受付の時刻だけ
- `POST /{pid}/unregister`: その端末の通知の登録と Cookie を消す。日付の印は消さない
- 記録の経路（POST・GET /entries、取り消し）は患者 API に無い
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from api_helpers import add_patient, api_client, db_conn, register
from fastapi.testclient import TestClient
from push_helpers import ENDPOINT, subscription_body, vapid_overrides

from tsutae import db
from tsutae.api import deps
from tsutae.config import PATIENT_STRINGS_PATH, jst_datetime, now

C1 = [(1, date(2026, 10, 27))]
C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C3)
    assert register(client, patient_id).status_code == 200
    return patient_id


# ---------------------------------------------------------------------------
# 固定規則
# ---------------------------------------------------------------------------


def test_questions_have_fixed_rules(client: TestClient, pid: str) -> None:
    body = client.get(f"/api/patient/{pid}/questions").json()
    assert body["fixed_rules"] == [
        {
            "question_key": "fever",
            "threshold_celsius": 38.0,
            "patient_string_key": "fixed_rule.fever_38",
        }
    ]
    assert set(body) == {"skill_version", "questions", "today", "fixed_rules"}


def test_capox_has_fixed_rules_too(client: TestClient) -> None:
    patient_id = add_patient(client.app, "CAPOX", courses=C1)
    register(client, patient_id)
    body = client.get(f"/api/patient/{patient_id}/questions").json()
    assert [r["patient_string_key"] for r in body["fixed_rules"]] == [
        "fixed_rule.fever_38"
    ]


# ---------------------------------------------------------------------------
# 送る範囲
# ---------------------------------------------------------------------------


def test_window_starts_at_the_previous_course(client: TestClient, pid: str) -> None:
    r = client.get(f"/api/patient/{pid}/visit-window")
    assert r.status_code == 200
    assert r.json() == {"start": "2026-10-13", "end": "2026-11-09"}


def test_window_without_previous_course_starts_at_day1(client: TestClient) -> None:
    first = add_patient(client.app, courses=C1)
    register(client, first)
    r = client.get(f"/api/patient/{first}/visit-window")
    assert r.json() == {"start": "2026-10-27", "end": "2026-11-09"}


def test_window_ignores_courses_that_have_not_started(client: TestClient) -> None:
    """未来のコースが登録されていても、今コースは今日で決める。"""
    courses = [*C1, (2, date(2026, 11, 20))]
    patient_id = add_patient(client.app, courses=courses)
    register(client, patient_id)
    r = client.get(f"/api/patient/{patient_id}/visit-window")
    assert r.json() == {"start": "2026-10-27", "end": "2026-11-09"}


def test_window_without_course_is_409(client: TestClient) -> None:
    none = add_patient(client.app)
    register(client, none)
    r = client.get(f"/api/patient/{none}/visit-window")
    assert r.status_code == 409
    assert r.json() == {"error": "no_course"}


def test_window_of_other_patient_is_403(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    assert client.get(f"/api/patient/{other}/visit-window").status_code == 403


# ---------------------------------------------------------------------------
# 受診日
# ---------------------------------------------------------------------------


def _visit_row(client: TestClient, pid: str, no: str, visit_date: date, at: str) -> int:
    """受診を作り、受診日と受付の時刻を書き換える（時計に頼らず並びを決める）。"""
    expires = jst_datetime(date(2026, 11, 10), 9, 0)
    with db_conn(client.app) as conn:
        vid = db.create_visit(conn, pid, no, visit_date, expires, 1)
        with conn:
            conn.execute(
                "UPDATE visits SET visit_date = ?, created_at = ? WHERE id = ?",
                (visit_date.isoformat(), at, vid),
            )
    return vid


def test_visit_days_empty(client: TestClient, pid: str) -> None:
    r = client.get(f"/api/patient/{pid}/visit-days")
    assert r.status_code == 200
    assert r.json() == {"visits": []}


def test_visit_days_have_only_date_and_time(client: TestClient, pid: str) -> None:
    """受診日は日付と受付の時刻だけ（受付番号・状態・id・レポートは返さない）。新しい順。"""
    old = _visit_row(
        client, pid, "A-001", date(2026, 10, 27), "2026-10-27T09:05:00.000000+09:00"
    )
    new = _visit_row(
        client, pid, "A-002", date(2026, 11, 9), "2026-11-09T09:40:00.000000+09:00"
    )
    with db_conn(client.app) as conn:
        db.set_visit_status(conn, old, "failed")
        db.set_visit_status(conn, new, "ready")
    r = client.get(f"/api/patient/{pid}/visit-days")
    assert r.status_code == 200
    assert r.json() == {
        "visits": [
            {"visit_date": "2026-11-09", "received_at": "2026-11-09T09:40:00+09:00"},
            {"visit_date": "2026-10-27", "received_at": "2026-10-27T09:05:00+09:00"},
        ]
    }
    for leaked in ("A-001", "A-002", "failed", "ready", "reception_no", "status"):
        assert leaked not in r.text


def test_visit_days_after_post_visit(client: TestClient, pid: str) -> None:
    """受付（POST /api/visit）をした日が受診日になる（生成の状態を問わない）。"""
    assert client.post("/api/visit", json={"reception_no": "A-023"}).is_success
    (visit,) = client.get(f"/api/patient/{pid}/visit-days").json()["visits"]
    assert visit["visit_date"] == "2026-11-09"
    assert visit["received_at"].startswith("2026-11-09T")
    assert visit["received_at"].endswith("+09:00")


def test_visit_days_only_own(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    _visit_row(
        client, other, "B-001", date(2026, 11, 9), "2026-11-09T09:00:00.000000+09:00"
    )
    assert client.get(f"/api/patient/{pid}/visit-days").json() == {"visits": []}
    assert client.get(f"/api/patient/{other}/visit-days").status_code == 403


# ---------------------------------------------------------------------------
# 登録を消す
# ---------------------------------------------------------------------------


@pytest.fixture
def push_client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path, **vapid_overrides()) as c:
        yield c


def _unregister(client: TestClient, pid: str, endpoint: str | None) -> object:
    return client.post(f"/api/patient/{pid}/unregister", json={"endpoint": endpoint})


def test_unregister_clears_the_cookie(client: TestClient, pid: str) -> None:
    r = _unregister(client, pid, None)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    header = r.headers["set-cookie"]
    assert header.startswith(f"{deps.PATIENT_COOKIE}=")
    assert "Max-Age=0" in header
    assert deps.PATIENT_COOKIE not in client.cookies
    assert client.get(f"/api/patient/{pid}/questions").status_code == 401


def test_unregister_keeps_the_marks(client: TestClient, pid: str) -> None:
    with db_conn(client.app) as conn:
        db.add_record_mark(conn, pid, now())
    assert _unregister(client, pid, None).status_code == 200
    with db_conn(client.app) as conn:
        assert pid in db.marked_patients(conn, date(2026, 11, 9))


def test_unregister_removes_this_subscription(push_client: TestClient) -> None:
    pid = add_patient(push_client.app, courses=C1)
    assert register(push_client, pid).status_code == 200
    url = f"/api/patient/{pid}/push-subscription"
    other_endpoint = f"{ENDPOINT}-other"
    assert push_client.put(url, json=subscription_body()).status_code == 200
    other_body = subscription_body(endpoint=other_endpoint)
    assert push_client.put(url, json=other_body).status_code == 200
    assert _unregister(push_client, pid, ENDPOINT).status_code == 200
    with db_conn(push_client.app) as conn:
        assert db.get_push_subscription(conn, pid, ENDPOINT) is None
        assert db.get_push_subscription(conn, pid, other_endpoint) is not None


def test_unregister_with_unknown_endpoint_is_ok(client: TestClient, pid: str) -> None:
    assert _unregister(client, pid, ENDPOINT).status_code == 200


def test_unregister_does_not_touch_other_patients(push_client: TestClient) -> None:
    other = add_patient(push_client.app, courses=C1)
    assert register(push_client, other).status_code == 200
    url = f"/api/patient/{other}/push-subscription"
    assert push_client.put(url, json=subscription_body()).status_code == 200
    pid = add_patient(push_client.app, courses=C1)
    assert register(push_client, pid).status_code == 200
    assert _unregister(push_client, pid, ENDPOINT).status_code == 200
    with db_conn(push_client.app) as conn:
        assert db.get_push_subscription(conn, other, ENDPOINT) is not None


@pytest.mark.parametrize(
    "body", [{}, {"endpoint": 1}, {"endpoint": None, "x": 1}, {"endpoint": "x" * 3000}]
)
def test_unregister_bad_body_is_422(client: TestClient, pid: str, body: dict) -> None:
    r = client.post(f"/api/patient/{pid}/unregister", json=body)
    assert r.status_code == 422
    assert deps.PATIENT_COOKIE in client.cookies


def test_reset_strings_say_only_the_current_number_is_deleted() -> None:
    """消すのは今の番号の記録だけ（§5.9）。端末の記録が全て消えたと思わせない。"""
    strings = json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))
    assert "今の番号の記録" in strings["device_reset.about"]
    assert "別の番号" in strings["device_reset.about"]
    assert "今の番号の記録" in strings["device_reset.confirm_first"]
    assert "その番号の記録" in strings["device_reset.done"]
    assert "このスマホに入っている記録" not in strings["device_reset.about"]


def test_unregister_other_patient_is_403(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    assert _unregister(client, other, None).status_code == 403
    assert deps.PATIENT_COOKIE in client.cookies


def test_unregister_without_cookie_is_401(client: TestClient, pid: str) -> None:
    client.cookies.clear()
    assert _unregister(client, pid, None).status_code == 401


# ---------------------------------------------------------------------------
# 外した経路
# ---------------------------------------------------------------------------


def test_entries_routes_are_gone(client: TestClient, pid: str) -> None:
    url = f"/api/patient/{pid}/entries"
    assert client.get(url).status_code == 404
    assert client.post(url, json={"too_sick": True}).status_code == 404
    assert client.post(f"{url}/1/undo").status_code == 404
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []

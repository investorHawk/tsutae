"""医師 API: 医師画面の UX の見直しで足した項目（Day・記録の途切れ・受診の見出し）。

- `GET /api/doctor/patients` の各患者に current_day（今日の今のコースでの Day）・
  days_since_last_record（今日 − 最後の記録日。記録が無ければ null）・record_stale
  （最後の記録が今日から3日以上前、または記録が1件も無い）。今日は `config.today()`
- `GET /api/doctor/patients/{pid}/entries` の各記録に course_no・day（記録日のコースと
  Day。コース外・コースの矛盾は null）
- `GET /api/doctor/visits/{id}/unprocessed` に visit（受付番号・仮名ID・受付の時刻・状態・
  レポートを開けるか）と、各記録の course_no・day
- `GET /api/doctor/pipeline/{id}/events` に同じ visit（印刷済みなら受付番号は null）
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from api_helpers import (
    add_entry,
    add_patient,
    api_client,
    db_conn,
    login_doctor,
    register,
)
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.config import jst_datetime
from tsutae.schemas import EntryCreate

C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
VISIT_HEADER_KEYS = {
    "id",
    "reception_no",
    "patient_id",
    "visit_date",
    "created_at",
    "status",
    "fallback",
    "report_available",
}


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        login_doctor(c)
        yield c


def _entry_on(client: TestClient, pid: str, day: date, hh: int = 9) -> int:
    with db_conn(client.app) as conn:
        saved = db.add_entry(
            conn,
            pid,
            EntryCreate(too_sick=True),
            jst_datetime(day, hh),
            "regimen-folfox@1",
        )
    return saved.id


def _patient_row(client: TestClient) -> dict[str, Any]:
    return client.get("/api/doctor/patients").json()["patients"][0]


def _visit(client: TestClient, pid: str, reception_no: str) -> dict[str, Any]:
    register(client, pid)
    r = client.post("/api/visit", json={"reception_no": reception_no})
    assert r.status_code == 200
    with db_conn(client.app) as conn:
        return db.list_visits(conn)[-1]


# ---------------------------------------------------------------------------
# 患者一覧: 今のコースの Day
# ---------------------------------------------------------------------------


def test_list_patients_has_current_day(client: TestClient) -> None:
    """今日 2026-11-09 は第3コース（Day1 = 10-27）の Day14。"""
    add_patient(client.app, courses=C3)
    patient = _patient_row(client)
    assert patient["current_course_no"] == 3
    assert patient["current_day"] == 14


def test_list_patients_current_day_null_without_course(client: TestClient) -> None:
    add_patient(client.app)
    assert _patient_row(client)["current_day"] is None


def test_list_patients_current_day_null_on_conflict(client: TestClient) -> None:
    """コースに矛盾（実投与日が逆順）があれば、その患者の今のコースと Day は null。"""
    add_patient(client.app, courses=[(1, date(2026, 10, 27)), (2, date(2026, 10, 13))])
    patient = _patient_row(client)
    assert patient["current_course_no"] is None
    assert patient["current_day"] is None


# ---------------------------------------------------------------------------
# 患者一覧: 記録の途切れ（3日以上前・記録なし）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("last", "days", "stale"),
    [
        (date(2026, 11, 9), 0, False),
        (date(2026, 11, 7), 2, False),
        (date(2026, 11, 6), 3, True),  # 今日を含めず3日前 → 途切れ
        (date(2026, 10, 28), 12, True),
    ],
)
def test_list_patients_record_stale(
    client: TestClient, last: date, days: int, stale: bool
) -> None:
    pid = add_patient(client.app, courses=C3)
    _entry_on(client, pid, date(2026, 10, 20))
    _entry_on(client, pid, last)
    patient = _patient_row(client)
    assert patient["last_record_date"] == last.isoformat()
    assert patient["days_since_last_record"] == days
    assert patient["record_stale"] is stale


def test_list_patients_without_records_is_stale(client: TestClient) -> None:
    add_patient(client.app, courses=C3)
    patient = _patient_row(client)
    assert patient["last_record_date"] is None
    assert patient["days_since_last_record"] is None
    assert patient["record_stale"] is True


def test_list_patients_stale_uses_config_today(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-07")
    with api_client(tmp_path) as c:
        login_doctor(c)
        pid = add_patient(c.app, courses=C3)
        _entry_on(c, pid, date(2026, 11, 6))
        patient = _patient_row(c)
    assert patient["days_since_last_record"] == 1
    assert patient["record_stale"] is False
    assert patient["current_day"] == 12


# ---------------------------------------------------------------------------
# 患者の記録: 記録日のコースと Day
# ---------------------------------------------------------------------------


def test_patient_entries_have_course_and_day(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    _entry_on(client, pid, date(2026, 11, 5))  # 第3コース Day10
    _entry_on(client, pid, date(2026, 10, 26))  # 第2コース Day14（次の前日）
    _entry_on(client, pid, date(2026, 9, 20))  # 最初の投与の前
    entries = client.get(f"/api/doctor/patients/{pid}/entries").json()["entries"]
    assert [(e["record_date"], e["course_no"], e["day"]) for e in entries] == [
        ("2026-11-05", 3, 10),
        ("2026-10-26", 2, 14),
        ("2026-09-20", None, None),
    ]


def test_patient_entries_day_continues_after_cycle(client: TestClient) -> None:
    """次のコースが未登録なら、cycle_days を過ぎても今のコースの Day を数え続ける。"""
    pid = add_patient(client.app, courses=[(1, date(2026, 10, 1))])
    _entry_on(client, pid, date(2026, 11, 1))
    entry = client.get(f"/api/doctor/patients/{pid}/entries").json()["entries"][0]
    assert (entry["course_no"], entry["day"]) == (1, 32)


def test_patient_entries_day_null_on_conflict(client: TestClient) -> None:
    pid = add_patient(
        client.app, courses=[(1, date(2026, 10, 27)), (2, date(2026, 10, 13))]
    )
    _entry_on(client, pid, date(2026, 11, 5))
    r = client.get(f"/api/doctor/patients/{pid}/entries")
    assert r.status_code == 200
    entry = r.json()["entries"][0]
    assert entry["course_no"] is None
    assert entry["day"] is None


# ---------------------------------------------------------------------------
# 未処理: 受診の見出しと、記録の Day
# ---------------------------------------------------------------------------


def test_unprocessed_has_visit_header_and_day(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    with db_conn(client.app) as conn:
        db.add_entry(
            conn,
            pid,
            EntryCreate(free_text="磯鷲さんにもらった漢方をのんでみた"),
            jst_datetime(date(2026, 11, 5), 20),
            "regimen-folfox@1",
        )
    visit = _visit(client, pid, "A-023")
    body = client.get(f"/api/doctor/visits/{visit['id']}/unprocessed").json()
    header = body["visit"]
    assert set(header) == VISIT_HEADER_KEYS
    assert header["id"] == visit["id"]
    assert header["reception_no"] == "A-023"
    assert header["patient_id"] == pid
    assert header["visit_date"] == "2026-11-09"
    assert header["created_at"] == visit["created_at"].isoformat()
    assert header["status"] == "ready"
    assert header["report_available"] is True
    entry = body["entries"][0]
    assert entry["record_date"] == "2026-11-05"
    assert (entry["course_no"], entry["day"]) == (3, 10)


def test_unprocessed_of_generating_visit_cannot_open_report(
    client: TestClient,
) -> None:
    pid = add_patient(client.app, courses=C3)
    with db_conn(client.app) as conn:
        vid = db.create_visit(
            conn,
            pid,
            "B-1",
            date(2026, 11, 9),
            jst_datetime(date(2026, 11, 10), 10),
            3,
        )
    body = client.get(f"/api/doctor/visits/{vid}/unprocessed").json()
    assert body["entries"] == []
    assert body["visit"]["status"] == "generating"
    assert body["visit"]["report_available"] is False


# ---------------------------------------------------------------------------
# 変換ログ: 受診の見出し
# ---------------------------------------------------------------------------


def test_pipeline_events_have_visit_header(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    visit = _visit(client, pid, "A-023")
    body = client.get(f"/api/doctor/pipeline/{visit['id']}/events").json()
    assert set(body) == {"status", "events", "visit"}
    assert set(body["visit"]) == VISIT_HEADER_KEYS
    assert body["visit"]["reception_no"] == "A-023"
    assert body["visit"]["patient_id"] == pid
    assert body["visit"]["report_available"] is True


def test_pipeline_events_of_printed_visit_has_no_reception_no(
    client: TestClient,
) -> None:
    pid = add_patient(client.app, courses=C3)
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    visit = _visit(client, pid, "A-023")
    assert client.post(f"/api/doctor/visits/{visit['id']}/printed").status_code == 200
    header = client.get(f"/api/doctor/pipeline/{visit['id']}/events").json()["visit"]
    assert header["reception_no"] is None
    assert header["status"] == "printed"
    assert header["report_available"] is False
    assert header["patient_id"] == pid

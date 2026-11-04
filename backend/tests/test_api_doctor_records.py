"""医師 API: 患者一覧の追加項目（D3-2）・患者ごとの受診と記録（D4-1）・未処理の印（D7-2）。

- `GET /api/doctor/patients` の各患者に last_record_date・current_course_no・next_visit
  （今日は `config.today()`。無ければ null）
- `GET /api/doctor/patients/{pid}/visits`: その患者の受診を新しい順に全部（印刷済み・
  期限切れも。受付番号は消えていれば null。レポートを開けるのは開いている ready だけ）
- `GET /api/doctor/patients/{pid}/entries`: 直近の記録（新しい順）。自由記載は有無だけで
  原文は返さない（原文は D6 だけ）
- `GET /api/doctor/visits/{id}/unprocessed` の各記録に marks（原文 text の中の疑われた語の
  位置。code point の [start, end)）
"""

from __future__ import annotations

from datetime import date, timedelta
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
from tsutae.config import jst_datetime, now
from tsutae.schemas import ClosedAnswer, Course, EntryCreate

C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        login_doctor(c)
        yield c


def _entry_at(
    client: TestClient, pid: str, entry: EntryCreate, day: date, hh: int = 9
) -> int:
    with db_conn(client.app) as conn:
        saved = db.add_entry(
            conn, pid, entry, jst_datetime(day, hh), "regimen-folfox@1"
        )
    return saved.id


def _visit(client: TestClient, pid: str, reception_no: str) -> dict[str, Any]:
    register(client, pid)
    r = client.post("/api/visit", json={"reception_no": reception_no})
    assert r.status_code == 200
    with db_conn(client.app) as conn:
        return db.list_visits(conn)[-1]


# ---------------------------------------------------------------------------
# D3-2 患者一覧の追加項目
# ---------------------------------------------------------------------------


def test_list_patients_has_record_course_and_next_visit(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    with db_conn(client.app) as conn:
        db.upsert_course(
            conn,
            Course(
                patient_id=pid,
                course_no=3,
                infusion_date=date(2026, 10, 27),
                next_visit=date(2026, 11, 10),
            ),
        )
    _entry_at(client, pid, EntryCreate(too_sick=True), date(2026, 11, 2))
    _entry_at(client, pid, EntryCreate(too_sick=True), date(2026, 11, 5))
    _entry_at(client, pid, EntryCreate(too_sick=True), date(2026, 10, 30))
    patient = client.get("/api/doctor/patients").json()["patients"][0]
    assert patient["last_record_date"] == "2026-11-05"
    assert patient["current_course_no"] == 3  # 今日 2026-11-09 は第3コース
    assert patient["next_visit"] == "2026-11-10"


def test_list_patients_without_records_or_courses_is_null(client: TestClient) -> None:
    add_patient(client.app)
    patient = client.get("/api/doctor/patients").json()["patients"][0]
    assert patient["last_record_date"] is None
    assert patient["current_course_no"] is None
    assert patient["next_visit"] is None


def test_list_patients_course_not_started_yet_is_null(client: TestClient) -> None:
    """最初の実投与日が今日より後なら今のコースは無い（次回受診も出さない）。"""
    add_patient(client.app, courses=[(1, date(2026, 11, 20))])
    patient = client.get("/api/doctor/patients").json()["patients"][0]
    assert patient["current_course_no"] is None
    assert patient["next_visit"] is None


def test_list_patients_uses_config_today(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """今日は `config.today()`（TSUTAE_TODAY）。ログインの前に日付を変える。"""
    monkeypatch.setenv("TSUTAE_TODAY", "2026-10-20")
    with api_client(tmp_path) as c:
        login_doctor(c)
        add_patient(c.app, courses=C3)
        patient = c.get("/api/doctor/patients").json()["patients"][0]
    assert patient["current_course_no"] == 2


# ---------------------------------------------------------------------------
# D4-1 患者ごとの受診
# ---------------------------------------------------------------------------

PATIENT_VISIT_KEYS = {
    "id",
    "reception_no",
    "visit_date",
    "created_at",
    "status",
    "fallback",
    "report_available",
    "unprocessed_count",
}


def test_patient_visits_newest_first_with_printed(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    other = add_patient(client.app, courses=C3)
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    first = _visit(client, pid, "A-001")
    client.post(f"/api/doctor/visits/{first['id']}/printed")
    second = _visit(client, pid, "A-002")
    _visit(client, other, "A-003")
    r = client.get(f"/api/doctor/patients/{pid}/visits")
    assert r.status_code == 200
    visits = r.json()["visits"]
    assert [v["id"] for v in visits] == [second["id"], first["id"]]
    assert set(visits[0]) == PATIENT_VISIT_KEYS
    assert visits[0]["reception_no"] == "A-002"
    assert visits[0]["status"] == "ready"
    assert visits[0]["report_available"] is True
    assert visits[0]["visit_date"] == "2026-11-09"
    assert visits[0]["created_at"].endswith("+09:00")
    # 印刷済みは受付番号もレポートも消えている
    assert visits[1]["reception_no"] is None
    assert visits[1]["status"] == "printed"
    assert visits[1]["report_available"] is False


def test_patient_visits_purges_expired_first(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path, report_ttl_hours=0) as c:
        login_doctor(c)
        pid = add_patient(c.app, courses=C3)
        add_entry(c.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
        _visit(c, pid, "A-001")
        visits = c.get(f"/api/doctor/patients/{pid}/visits").json()["visits"]
    assert visits[0]["reception_no"] is None
    assert visits[0]["report_available"] is False


def test_patient_visits_counts_unprocessed(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    add_entry(client.app, pid, EntryCreate(free_text="磯鷲さんにもらった漢方"))
    _visit(client, pid, "A-001")
    visits = client.get(f"/api/doctor/patients/{pid}/visits").json()["visits"]
    assert visits[0]["unprocessed_count"] == 1


def test_patient_visits_empty(client: TestClient) -> None:
    pid = add_patient(client.app)
    assert client.get(f"/api/doctor/patients/{pid}/visits").json() == {"visits": []}


# ---------------------------------------------------------------------------
# D4-1 患者ごとの記録
# ---------------------------------------------------------------------------

ENTRY_KEYS = {
    "id",
    "recorded_at",
    "record_date",
    "kind",
    "by_proxy",
    "answers",
    "has_free_text",
}


def test_patient_entries_newest_first_without_raw_text(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    answers = [
        ClosedAnswer(question_key="fever", value="measured", temperature=38.2),
        ClosedAnswer(question_key="diarrhea", value="present"),
    ]
    old = _entry_at(client, pid, EntryCreate(too_sick=True), date(2026, 11, 1))
    new = _entry_at(
        client,
        pid,
        EntryCreate(by_proxy=True, answers=answers, free_text="磯鷲さんにもらった"),
        date(2026, 11, 3),
    )
    r = client.get(f"/api/doctor/patients/{pid}/entries")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    entries = body["entries"]
    assert [e["id"] for e in entries] == [new, old]
    assert set(entries[0]) == ENTRY_KEYS
    assert entries[0]["record_date"] == "2026-11-03"
    assert entries[0]["kind"] == "mixed"
    assert entries[0]["by_proxy"] is True
    assert entries[0]["has_free_text"] is True
    assert entries[0]["answers"] == [
        {"question_key": "fever", "value": "measured", "temperature": 38.2},
        {"question_key": "diarrhea", "value": "present", "temperature": None},
    ]
    assert entries[1]["kind"] == "too_sick"
    assert entries[1]["has_free_text"] is False
    assert "磯鷲" not in r.text  # 原文は D6 だけ


def test_patient_entries_limited_to_recent(client: TestClient) -> None:
    from tsutae.api.doctor_records import RECENT_ENTRIES_MAX

    pid = add_patient(client.app)
    start = date(2026, 9, 1)
    for n in range(RECENT_ENTRIES_MAX + 2):
        _entry_at(client, pid, EntryCreate(too_sick=True), start + timedelta(days=n))
    body = client.get(f"/api/doctor/patients/{pid}/entries").json()
    assert body["total"] == RECENT_ENTRIES_MAX + 2
    assert len(body["entries"]) == RECENT_ENTRIES_MAX
    last = start + timedelta(days=RECENT_ENTRIES_MAX + 1)
    assert body["entries"][0]["record_date"] == last.isoformat()


def test_patient_entries_only_that_patient(client: TestClient) -> None:
    pid = add_patient(client.app)
    other = add_patient(client.app)
    add_entry(client.app, other, EntryCreate(too_sick=True))
    assert client.get(f"/api/doctor/patients/{pid}/entries").json() == {
        "entries": [],
        "total": 0,
    }


@pytest.mark.parametrize("route", ["visits", "entries"])
@pytest.mark.parametrize("pid", ["P-ZZZZZZZZ", "p-aaaaaaaa", "nope"])
def test_patient_records_unknown_patient_is_404(
    client: TestClient, route: str, pid: str
) -> None:
    r = client.get(f"/api/doctor/patients/{pid}/{route}")
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_patient"}


@pytest.mark.parametrize("route", ["visits", "entries"])
def test_patient_records_need_doctor(tmp_path: Path, fixed_today: str, route: str):
    with api_client(tmp_path) as c:
        pid = add_patient(c.app)
        r = c.get(f"/api/doctor/patients/{pid}/{route}")
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


# ---------------------------------------------------------------------------
# D7-2 未処理の印
# ---------------------------------------------------------------------------


def test_unprocessed_marks_suspected_word(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    raw = "磯鷲さんにもらった漢方をのんでみた。おなかがあったかい感じ"
    add_entry(client.app, pid, EntryCreate(free_text=raw))
    vid = _visit(client, pid, "A-023")["id"]
    entries = client.get(f"/api/doctor/visits/{vid}/unprocessed").json()["entries"]
    assert entries[0]["reason"] == "unknown_before_honorific"
    assert entries[0]["marks"] == [{"start": 0, "end": 4}]


def test_unprocessed_marks_known_identifier(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    raw = f"紙に{pid}と書いてあった"
    add_entry(client.app, pid, EntryCreate(free_text=raw))
    vid = _visit(client, pid, "A-023")["id"]
    entries = client.get(f"/api/doctor/visits/{vid}/unprocessed").json()["entries"]
    assert entries[0]["reason"] == "known_identifier"
    assert entries[0]["marks"] == [{"start": 2, "end": 2 + len(pid)}]


def test_now_is_fixed(fixed_today: str) -> None:
    """このファイルの日付の前提（今日 = 2026-11-09）。"""
    assert now().date() == date(2026, 11, 9)

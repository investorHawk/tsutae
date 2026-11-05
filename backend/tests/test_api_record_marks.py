"""記録のときの日付の印と取り消し（plan-device-records §5.2・§5.4）。

- `POST /{pid}/record-marks`（本文なし）: サーバーの時計で今日の印を付け、記録日と時刻を返す
- `POST /{pid}/record-marks/undo`（`{recorded_at, clear_mark}`）: サーバーの時計で 10 分以内で、
  その後に受付が無ければ通す。外れれば 409 not_undoable。clear_mark なら印を消す
- サーバーは記録の種類を知らない。端末の記録を消すのは端末（この応答を見てから）
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import add_entry, add_patient, api_client, db_conn, register
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.api import patient_device
from tsutae.config import JST, jst_datetime, now
from tsutae.schemas import EntryCreate

C1 = [(1, date(2026, 10, 27))]
TODAY = date(2026, 11, 9)


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C1)
    assert register(client, patient_id).status_code == 200
    return patient_id


def _mark(client: TestClient, pid: str) -> dict[str, str]:
    r = client.post(f"/api/patient/{pid}/record-marks")
    assert r.status_code == 200, r.text
    return r.json()


def _undo(client: TestClient, pid: str, recorded_at: str, clear: bool = True) -> Any:
    return client.post(
        f"/api/patient/{pid}/record-marks/undo",
        json={"recorded_at": recorded_at, "clear_mark": clear},
    )


def _marked(client: TestClient, pid: str, day: date = TODAY) -> bool:
    with db_conn(client.app) as conn:
        return pid in db.marked_patients(conn, day)


def _later(monkeypatch: pytest.MonkeyPatch, delta: timedelta) -> None:
    """印の経路の時計だけを delta 進める。"""
    start = now()
    monkeypatch.setattr(patient_device, "now", lambda: start + delta)


# ---------------------------------------------------------------------------
# 印
# ---------------------------------------------------------------------------


def test_mark_returns_server_date_and_time(client: TestClient, pid: str) -> None:
    body = _mark(client, pid)
    assert set(body) == {"record_date", "recorded_at"}
    assert body["record_date"] == "2026-11-09"
    at = datetime.fromisoformat(body["recorded_at"])
    assert at.utcoffset() == timedelta(hours=9)
    assert at.date() == TODAY
    assert _marked(client, pid)


def test_mark_ignores_the_body(client: TestClient, pid: str) -> None:
    """体温や回答を送っても読まない（端末の時計・中身をサーバーに渡す欄が無い）。"""
    r = client.post(
        f"/api/patient/{pid}/record-marks",
        json={"record_date": "2020-01-01", "free_text": "（合成）読まない"},
    )
    assert r.status_code == 200
    assert r.json()["record_date"] == "2026-11-09"
    assert "読まない" not in r.text
    assert not _marked(client, pid, date(2020, 1, 1))


def test_mark_writes_no_entries(client: TestClient, pid: str) -> None:
    _mark(client, pid)
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []


def test_mark_twice_keeps_one_mark_with_the_later_time(
    client: TestClient, pid: str
) -> None:
    first = _mark(client, pid)
    second = _mark(client, pid)
    assert second["recorded_at"] >= first["recorded_at"]
    with db_conn(client.app) as conn:
        rows = conn.execute("SELECT * FROM record_marks").fetchall()
    assert len(rows) == 1
    assert rows[0]["last_marked_at"] == second["recorded_at"]


def test_mark_other_patient_is_403(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    r = client.post(f"/api/patient/{other}/record-marks")
    assert r.status_code == 403
    assert not _marked(client, other)


def test_mark_without_cookie_is_401(client: TestClient, pid: str) -> None:
    client.cookies.clear()
    assert client.post(f"/api/patient/{pid}/record-marks").status_code == 401
    assert not _marked(client, pid)


# ---------------------------------------------------------------------------
# 取り消し
# ---------------------------------------------------------------------------


def test_undo_window_is_ten_minutes() -> None:
    assert timedelta(minutes=10) == patient_device.UNDO_WINDOW


def test_undo_clears_the_mark(client: TestClient, pid: str) -> None:
    body = _mark(client, pid)
    r = _undo(client, pid, body["recorded_at"])
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert not _marked(client, pid)


def test_undo_with_the_time_read_by_the_browser_clears_the_mark(
    client: TestClient, pid: str
) -> None:
    """端末が時刻を Date に通して送り直しても（UTC・ミリ秒）同じ時刻として通る。"""
    body = _mark(client, pid)
    at = datetime.fromisoformat(body["recorded_at"])
    browser = at.astimezone(UTC).isoformat(timespec="milliseconds")
    assert _undo(client, pid, browser).status_code == 200
    assert not _marked(client, pid)


def test_undo_without_clear_keeps_the_mark(client: TestClient, pid: str) -> None:
    body = _mark(client, pid)
    assert _undo(client, pid, body["recorded_at"], clear=False).status_code == 200
    assert _marked(client, pid)


def test_undo_twice_is_still_ok(client: TestClient, pid: str) -> None:
    """応答が届かず押し直しても失敗にしない（端末の記録を消せるように）。"""
    body = _mark(client, pid)
    assert _undo(client, pid, body["recorded_at"]).status_code == 200
    assert _undo(client, pid, body["recorded_at"]).status_code == 200


def test_undo_allowed_just_inside_the_window(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _mark(client, pid)
    _later(monkeypatch, patient_device.UNDO_WINDOW - timedelta(seconds=5))
    assert _undo(client, pid, body["recorded_at"]).status_code == 200
    assert not _marked(client, pid)


def test_undo_refused_after_the_window(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _mark(client, pid)
    _later(monkeypatch, patient_device.UNDO_WINDOW + timedelta(seconds=1))
    r = _undo(client, pid, body["recorded_at"])
    assert r.status_code == 409
    assert r.json() == {"error": "not_undoable"}
    assert _marked(client, pid)


def test_undo_refused_for_a_future_time(client: TestClient, pid: str) -> None:
    """窓の内側に見せるために先の時刻を送っても通さない。"""
    _mark(client, pid)
    future = (now() + timedelta(minutes=5)).isoformat()
    assert _undo(client, pid, future).status_code == 409
    assert _marked(client, pid)


def test_undo_refused_after_a_visit(client: TestClient, pid: str) -> None:
    """受付の後は、その記録がレポートの材料になりうるので消さない。"""
    body = _mark(client, pid)
    assert client.post("/api/visit", json={"reception_no": "A-1"}).is_success
    r = _undo(client, pid, body["recorded_at"])
    assert r.status_code == 409
    assert r.json() == {"error": "not_undoable"}
    assert _marked(client, pid)


def test_undo_allowed_when_the_visit_was_before(client: TestClient, pid: str) -> None:
    assert client.post("/api/visit", json={"reception_no": "A-1"}).is_success
    body = _mark(client, pid)
    assert _undo(client, pid, body["recorded_at"]).status_code == 200
    assert not _marked(client, pid)


def test_undo_clears_the_day_of_the_record_across_midnight(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0時をまたいだ取り消しは、その記録の日の印を消す（今日の印は残す）。"""
    late = jst_datetime(TODAY, 0, 0) - timedelta(minutes=2)
    with db_conn(client.app) as conn:
        db.add_record_mark(conn, pid, late)
        db.add_record_mark(conn, pid, late + timedelta(minutes=3))
    monkeypatch.setattr(patient_device, "now", lambda: late + timedelta(minutes=5))
    assert _undo(client, pid, late.isoformat()).status_code == 200
    assert not _marked(client, pid, TODAY - timedelta(days=1))
    assert _marked(client, pid, TODAY)


def test_undo_keeps_a_mark_written_later(client: TestClient, pid: str) -> None:
    """別の端末が後から書いた日は、取り消しでも印を消さない。"""
    first = _mark(client, pid)
    _mark(client, pid)
    with db_conn(client.app) as conn, conn:
        conn.execute(
            "UPDATE record_marks SET last_marked_at = ?",
            ((now() + timedelta(seconds=1)).isoformat(timespec="microseconds"),),
        )
    assert _undo(client, pid, first["recorded_at"]).status_code == 200
    assert _marked(client, pid)


def test_undo_touches_only_this_patient(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    with db_conn(client.app) as conn:
        db.add_record_mark(conn, other, now())
    body = _mark(client, pid)
    assert _undo(client, pid, body["recorded_at"]).status_code == 200
    assert _marked(client, other)


def test_undo_does_not_touch_entries(client: TestClient, pid: str) -> None:
    add_entry(client.app, pid, EntryCreate(too_sick=True))
    body = _mark(client, pid)
    assert _undo(client, pid, body["recorded_at"]).status_code == 200
    with db_conn(client.app) as conn:
        assert len(db.list_entries(conn, pid)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"recorded_at": "x", "clear_mark": True},
        {"recorded_at": "2026-11-09T20:00:00", "clear_mark": True},  # 時差なし
        {"recorded_at": "2026-11-09T20:00:00+09:00"},
        {"clear_mark": True},
        {"recorded_at": "2026-11-09T20:00:00+09:00", "clear_mark": "x"},
        {"recorded_at": "2026-11-09T20:00:00+09:00", "clear_mark": True, "x": 1},
    ],
)
def test_undo_bad_body_is_422(client: TestClient, pid: str, body: dict) -> None:
    r = client.post(f"/api/patient/{pid}/record-marks/undo", json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


def test_undo_other_patient_is_403(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    with db_conn(client.app) as conn:
        db.add_record_mark(conn, other, now())
    assert _undo(client, other, now().isoformat()).status_code == 403
    assert _marked(client, other)


def test_undo_without_cookie_is_401(client: TestClient, pid: str) -> None:
    body = _mark(client, pid)
    client.cookies.clear()
    assert _undo(client, pid, body["recorded_at"]).status_code == 401
    assert _marked(client, pid)


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------


def test_db_undo_is_refused_with_a_visit_at_the_same_time(
    client: TestClient, pid: str
) -> None:
    at = datetime(2026, 11, 9, 9, 0, tzinfo=JST)
    expires = at + timedelta(hours=24)
    with db_conn(client.app) as conn:
        db.add_record_mark(conn, pid, at)
        db.create_visit(conn, pid, "A-1", TODAY, expires, 1)
        with conn:
            conn.execute(
                "UPDATE visits SET created_at = ?", (at.isoformat("T", "microseconds"),)
            )
        assert not db.undo_record_mark(conn, pid, at, clear_mark=True)
        assert pid in db.marked_patients(conn, TODAY)

"""患者の受付の送り直し（タイムアウトの後）で二重にしないこと。記録の ID は test_api_visit_entries。

- `POST /api/visit`: 同じ患者で、受付番号が残っていて期限内の受診が今日すでにあり、
  正規化した受付番号が同じなら、新しく作らず、新しい記録が無ければ生成も起動しない
- 今日の印刷済みの受診があれば、番号を問わず 409（plan-device-records §6。test_api_second_device）
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import add_entry, add_patient, api_client, db_conn, register
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner

from tsutae import db
from tsutae.config import now, today
from tsutae.schemas import EntryCreate

C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def client(tmp_path: Path, fixed_today: str, runner: FakeRunner):
    with api_client(tmp_path, runner=runner) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C3)
    assert register(client, patient_id).status_code == 200
    return patient_id


def _entries(client: TestClient, pid: str) -> list[Any]:
    with db_conn(client.app) as conn:
        return db.list_entries(conn, pid)


def _visits(client: TestClient) -> list[dict[str, Any]]:
    with db_conn(client.app) as conn:
        return db.list_visits(conn)


# ---------------------------------------------------------------------------
# 受診
# ---------------------------------------------------------------------------


def test_same_visit_twice_is_created_once(
    client: TestClient, pid: str, runner: FakeRunner
) -> None:
    add_entry(client.app, pid, EntryCreate(free_text="（合成）おなかがゆるい"))
    for body in ({"reception_no": "A-023"}, {"reception_no": "　Ａ－０２３ "}):
        r = client.post("/api/visit", json=body)
        assert r.status_code == 200
        assert r.json() == {"ok": True, "message_key": "visit.done"}
    assert len(_visits(client)) == 1
    assert runner.calls == 1
    assert client.app.state.runner_factory.calls == 1


def test_other_reception_no_creates_new_visit(
    client: TestClient, pid: str, runner: FakeRunner
) -> None:
    for no in ("A-023", "A-024"):
        assert client.post("/api/visit", json={"reception_no": no}).status_code == 200
    assert [v["reception_no"] for v in _visits(client)] == ["A-023", "A-024"]
    assert client.app.state.runner_factory.calls == 2


def test_printed_visit_is_not_reused(client: TestClient, pid: str) -> None:
    assert client.post("/api/visit", json={"reception_no": "A-023"}).status_code == 200
    (visit,) = _visits(client)
    with db_conn(client.app) as conn:
        db.mark_printed(conn, visit["id"])
    r = client.post("/api/visit", json={"reception_no": "A-023"})
    assert (r.status_code, r.json()) == (409, {"error": "already_printed"})
    assert len(_visits(client)) == 1
    assert client.app.state.runner_factory.calls == 1


def test_expired_visit_is_not_reused(client: TestClient, pid: str) -> None:
    with db_conn(client.app) as conn:
        db.create_visit(conn, pid, "A-023", today(), now() - timedelta(seconds=1), 3)
    assert client.post("/api/visit", json={"reception_no": "A-023"}).status_code == 200
    assert len(_visits(client)) == 2
    assert client.app.state.runner_factory.calls == 1


def test_yesterday_visit_is_not_reused(client: TestClient, pid: str) -> None:
    with db_conn(client.app) as conn:
        db.create_visit(
            conn,
            pid,
            "A-023",
            today() - timedelta(days=1),
            now() + timedelta(hours=1),
            3,
        )
    assert client.post("/api/visit", json={"reception_no": "A-023"}).status_code == 200
    assert len(_visits(client)) == 2


def test_other_patient_visit_is_not_reused(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C3)
    with db_conn(client.app) as conn:
        db.create_visit(conn, other, "A-023", today(), now() + timedelta(hours=1), 3)
    assert client.post("/api/visit", json={"reception_no": "A-023"}).status_code == 200
    assert len(_visits(client)) == 2
    assert client.app.state.runner_factory.calls == 1


def test_create_visit_once(client: TestClient, pid: str) -> None:
    expires = now() + timedelta(hours=24)
    with db_conn(client.app) as conn:
        first = db.create_visit_once(conn, pid, "A-9", today(), expires, 3)
        again = db.create_visit_once(conn, pid, "A-9", today(), expires, 3)
    assert first.created is True and again.created is False
    assert again.visit_id == first.visit_id

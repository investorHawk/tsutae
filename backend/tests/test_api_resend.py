"""患者の送り直し（タイムアウトの後）で二重にしないこと。

- `POST /api/patient/{pid}/entries`: 同じ患者・同じ内容の記録が直近 120 秒以内にあれば、
  新しく作らずその entry_id と notices を返す
- `POST /api/visit`: 同じ患者で、受付番号が残っていて期限内の受診が今日すでにあり、
  正規化した受付番号が同じなら、新しく作らず生成も起動しない
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
from tsutae.schemas import ClosedAnswer, EntryCreate

C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
FEVER = {
    "answers": [
        {"question_key": "fever", "value": "measured", "temperature": 38.2},
        {"question_key": "diarrhea", "value": "present"},
    ],
    "free_text": "（合成）だるい",
}


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
# 記録
# ---------------------------------------------------------------------------


def test_same_entry_twice_is_saved_once(client: TestClient, pid: str) -> None:
    url = f"/api/patient/{pid}/entries"
    first = client.post(url, json=FEVER)
    second = client.post(url, json=FEVER)
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert first.json()["notices"]  # 38.0 以上の注意も同じく返す
    assert len(_entries(client, pid)) == 1


def test_same_entry_normalized_is_saved_once(client: TestClient, pid: str) -> None:
    """回答の順・自由記載の前後の空白・既定値の有無が違っても同じ内容。"""
    url = f"/api/patient/{pid}/entries"
    first = client.post(url, json=FEVER)
    reordered = {
        "too_sick": False,
        "by_proxy": False,
        "answers": list(reversed(FEVER["answers"])),
        "free_text": "  （合成）だるい \n",
    }
    second = client.post(url, json=reordered)
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert len(_entries(client, pid)) == 1


def test_too_sick_twice_is_saved_once(client: TestClient, pid: str) -> None:
    url = f"/api/patient/{pid}/entries"
    ids = {client.post(url, json={"too_sick": True}).json()["entry_id"] for _ in "12"}
    assert len(ids) == 1
    assert len(_entries(client, pid)) == 1


@pytest.mark.parametrize(
    "other",
    [
        {**FEVER, "free_text": "（合成）だるい。少し"},
        {**FEVER, "by_proxy": True},
        {"answers": FEVER["answers"][:1], "free_text": FEVER["free_text"]},
        {"too_sick": True},
    ],
)
def test_different_entry_is_saved(client: TestClient, pid: str, other: dict) -> None:
    url = f"/api/patient/{pid}/entries"
    first = client.post(url, json=FEVER).json()["entry_id"]
    second = client.post(url, json=other).json()["entry_id"]
    assert first != second
    assert len(_entries(client, pid)) == 2


def test_same_entry_after_120_seconds_is_saved(client: TestClient, pid: str) -> None:
    entry = EntryCreate.model_validate(FEVER)
    with db_conn(client.app) as conn:
        old = db.add_entry(
            conn, pid, entry, now() - timedelta(seconds=121), "regimen-folfox@1"
        )
    r = client.post(f"/api/patient/{pid}/entries", json=FEVER)
    assert r.json()["entry_id"] != old.id
    assert len(_entries(client, pid)) == 2


def test_same_entry_of_other_patient_is_saved(client: TestClient, pid: str) -> None:
    entry = EntryCreate.model_validate(FEVER)
    other = add_patient(client.app, courses=C3)
    with db_conn(client.app) as conn:
        db.add_entry(conn, other, entry, now(), "regimen-folfox@1")
    r = client.post(f"/api/patient/{pid}/entries", json=FEVER)
    assert r.status_code == 200
    assert len(_entries(client, pid)) == 1
    assert len(_entries(client, other)) == 1


def test_add_entry_once_returns_existing(client: TestClient, pid: str) -> None:
    entry = EntryCreate(
        answers=[ClosedAnswer(question_key="nausea", value="present")],
        free_text="（合成）むかむか",
    )
    window = timedelta(seconds=120)
    with db_conn(client.app) as conn:
        at = now()
        first = db.add_entry_once(conn, pid, entry, at, "regimen-folfox@1", window)
        again = db.add_entry_once(
            conn, pid, entry, at + timedelta(seconds=119), "regimen-folfox@2", window
        )
        later = db.add_entry_once(
            conn, pid, entry, at + timedelta(seconds=121), "regimen-folfox@1", window
        )
    assert again.id == first.id
    assert again.skill_version == "regimen-folfox@1"  # 保存済みのものを返す
    assert later.id != first.id


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
    assert client.post("/api/visit", json={"reception_no": "A-023"}).status_code == 200
    assert len(_visits(client)) == 2
    assert client.app.state.runner_factory.calls == 2


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
        first, created = db.create_visit_once(conn, pid, "A-9", today(), expires, 3)
        again, created_again = db.create_visit_once(
            conn, pid, "A-9", today(), expires, 3
        )
    assert created is True and created_again is False
    assert again == first

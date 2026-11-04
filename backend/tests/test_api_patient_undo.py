"""「つらくて書けない」の取り消し（P2-5）。POST /api/patient/{pid}/entries/{id}/undo。

取り消せるのは、本人の・つらくて書けないの・作ってから UNDO_WINDOW 以内の・その後に
受診の受付が無い記録だけ。他人の記録は 404（有る無しを明かさない）、条件に合わなければ
409 not_undoable。押す前の確認は画面に入れない（先生の決定）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from api_helpers import add_entry, add_patient, api_client, db_conn, register
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.api import patient as patient_api
from tsutae.config import now
from tsutae.schemas import ClosedAnswer, EntryCreate

C1 = [(1, date(2026, 10, 27))]


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C1)
    assert register(client, patient_id).status_code == 200
    return patient_id


def _too_sick(client: TestClient, pid: str) -> int:
    r = client.post(f"/api/patient/{pid}/entries", json={"too_sick": True})
    assert r.status_code == 200
    return int(r.json()["entry_id"])


def _undo(client: TestClient, pid: str, entry_id: int | str):
    return client.post(f"/api/patient/{pid}/entries/{entry_id}/undo")


def _exists(client: TestClient, entry_id: int) -> bool:
    with db_conn(client.app) as conn:
        return db.get_entry(conn, entry_id) is not None


def _later(monkeypatch: pytest.MonkeyPatch, delta: timedelta) -> None:
    """患者 API の時計だけを delta 進める。"""
    start = now()
    monkeypatch.setattr(patient_api, "now", lambda: start + delta)


def test_undo_window_is_short() -> None:
    assert timedelta(0) < patient_api.UNDO_WINDOW <= timedelta(minutes=10)


def test_undo_deletes_own_fresh_too_sick(client: TestClient, pid: str) -> None:
    entry_id = _too_sick(client, pid)
    r = _undo(client, pid, entry_id)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert not _exists(client, entry_id)
    assert client.get(f"/api/patient/{pid}/entries").json()["entries"] == []


def test_undo_twice_is_404(client: TestClient, pid: str) -> None:
    entry_id = _too_sick(client, pid)
    assert _undo(client, pid, entry_id).status_code == 200
    r = _undo(client, pid, entry_id)
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


def test_undo_keeps_other_entries(client: TestClient, pid: str) -> None:
    kept = add_entry(client.app, pid, EntryCreate(free_text="きのうの記録"))
    entry_id = _too_sick(client, pid)
    assert _undo(client, pid, entry_id).status_code == 200
    assert _exists(client, kept)


def test_undo_refuses_answers_and_free_text(client: TestClient, pid: str) -> None:
    answers = add_entry(
        client.app,
        pid,
        EntryCreate(answers=[ClosedAnswer(question_key="diarrhea", value="hard")]),
    )
    free = add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい"))
    for entry_id in (answers, free):
        r = _undo(client, pid, entry_id)
        assert r.status_code == 409
        assert r.json() == {"error": "not_undoable"}
        assert _exists(client, entry_id)


def test_undo_refuses_after_the_window(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry_id = _too_sick(client, pid)
    _later(monkeypatch, patient_api.UNDO_WINDOW + timedelta(seconds=1))
    r = _undo(client, pid, entry_id)
    assert r.status_code == 409
    assert r.json() == {"error": "not_undoable"}
    assert _exists(client, entry_id)


def test_undo_allowed_just_inside_the_window(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry_id = _too_sick(client, pid)
    _later(monkeypatch, patient_api.UNDO_WINDOW - timedelta(seconds=5))
    assert _undo(client, pid, entry_id).status_code == 200
    assert not _exists(client, entry_id)


def test_undo_refuses_after_a_visit(client: TestClient, pid: str) -> None:
    """受付の後は、その記録がレポートの材料になりうるので消さない。"""
    entry_id = _too_sick(client, pid)
    with db_conn(client.app) as conn:
        expires = now() + timedelta(hours=24)
        db.create_visit(conn, pid, "A-023", now().date(), expires, 1)
    r = _undo(client, pid, entry_id)
    assert r.status_code == 409
    assert r.json() == {"error": "not_undoable"}
    assert _exists(client, entry_id)


def test_undo_other_patients_entry_is_404(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    theirs = add_entry(client.app, other, EntryCreate(too_sick=True))
    r = _undo(client, pid, theirs)
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}
    assert _exists(client, theirs)


def test_undo_with_other_patients_path_is_403(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    theirs = add_entry(client.app, other, EntryCreate(too_sick=True))
    r = _undo(client, other, theirs)
    assert r.status_code == 403
    assert _exists(client, theirs)


def test_undo_without_cookie_is_401(client: TestClient, pid: str) -> None:
    entry_id = _too_sick(client, pid)
    client.cookies.clear()
    assert _undo(client, pid, entry_id).status_code == 401
    assert _exists(client, entry_id)


@pytest.mark.parametrize("bad", ["0", "-1", "abc", str(2**63)])
def test_undo_bad_entry_id_is_422(client: TestClient, pid: str, bad: str) -> None:
    r = _undo(client, pid, bad)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


def test_unknown_entry_is_404(client: TestClient, pid: str) -> None:
    assert _undo(client, pid, 999).status_code == 404


# ---------------------------------------------------------------------------
# db.undo_too_sick_entry
# ---------------------------------------------------------------------------


def _since(minutes: int = 10) -> datetime:
    return now() - timedelta(minutes=minutes)


def test_db_undo_results(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    mine = add_entry(client.app, pid, EntryCreate(too_sick=True))
    theirs = add_entry(client.app, other, EntryCreate(too_sick=True))
    free = add_entry(client.app, pid, EntryCreate(free_text="ねむい"))
    with db_conn(client.app) as conn:
        assert db.undo_too_sick_entry(conn, pid, theirs, _since()) == "not_found"
        assert db.undo_too_sick_entry(conn, pid, free, _since()) == "not_undoable"
        future = now() + timedelta(seconds=1)
        assert db.undo_too_sick_entry(conn, pid, mine, future) == "not_undoable"
        assert db.undo_too_sick_entry(conn, pid, mine, _since()) == "deleted"
        assert db.get_entry(conn, mine) is None
        assert db.get_entry(conn, theirs) is not None
        assert db.get_entry(conn, free) is not None

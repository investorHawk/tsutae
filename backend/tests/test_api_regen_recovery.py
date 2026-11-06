"""2台目のスマホ（plan-device-records §6）の変換し直しが止まったときの動き。症例は全て合成。

Claude は呼ばない。

- 起動時・周期の回収は Claude を呼ばず全ての記録を読むので、自動の回数を使わない
- 変換し直しが failed で終わっても、前のレポートは D3 から開けて、印刷済みにできる
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import add_patient, api_client, db_conn, login_doctor, register
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner
from test_api_second_device import (
    C3,
    TEXT_A,
    TEXT_B,
    UUID_A,
    UUID_B,
    UUID_C,
    _add_from_other_phone,
    _events,
    _generating_visit,
    _only_visit,
    _post,
    _received,
    _row,
    _text,
    _too_sick,
    _use,
)

from tsutae import db
from tsutae.api import orphans, visit
from tsutae.pipeline import service


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        login_doctor(c)
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C3)
    assert register(client, patient_id).status_code == 200
    return patient_id


def _set_regen_count(client: TestClient, vid: int, count: int) -> None:
    with db_conn(client.app) as conn:
        conn.execute("UPDATE visits SET regen_count = ? WHERE id = ?", (count, vid))
        conn.commit()


def test_orphan_with_pending_uses_no_automatic_run_and_runs_once(
    client: TestClient, pid: str
) -> None:
    """回収は Claude を呼ばず、全ての記録を読む。費用の歯止めの枠を使わず、2周目も要らない。"""
    vid = _generating_visit(client, pid)
    assert _post(client, [_text(UUID_B, TEXT_B)]).status_code == 200
    settings = client.app.state.settings
    assert asyncio.run(orphans.recover_orphans(settings)) == 1
    only = _only_visit(client)
    assert (only["regen_pending"], only["regen_count"]) == (False, 0)
    names = [e["event"] for e in _events(client, vid)]
    assert names.count("run_start") == 1
    assert "regenerate_requested" not in names


def test_stale_recovery_with_pending_uses_no_automatic_run(
    client: TestClient, pid: str
) -> None:
    vid = _generating_visit(client, pid)
    assert _post(client, [_text(UUID_B, TEXT_B)]).status_code == 200
    settings = client.app.state.settings
    recovered = orphans.recover_stale(settings, stale_after=timedelta(0))
    assert asyncio.run(recovered) == 1
    only = _only_visit(client)
    assert (only["id"], only["status"]) == (vid, "ready")
    assert (only["regen_pending"], only["regen_count"]) == (False, 0)


def test_after_recovery_the_next_record_is_still_converted_automatically(
    client: TestClient, pid: str
) -> None:
    """回収の前に2回使っていても、次の記録には3回目の枠が残っている。"""
    factory = _use(client, FakeRunner())
    vid = _generating_visit(client, pid)
    _set_regen_count(client, vid, db.REGEN_AUTO_MAX - 1)
    assert _post(client, [_text(UUID_B, TEXT_B)]).status_code == 200
    settings = client.app.state.settings
    assert asyncio.run(orphans.recover_orphans(settings)) == 1
    assert _only_visit(client)["regen_count"] == db.REGEN_AUTO_MAX - 1

    assert _post(client, [_text(UUID_C, TEXT_A)]).status_code == 200
    assert factory.calls == 1
    only = _only_visit(client)
    assert only["status"] == "ready"
    assert (only["regen_pending"], only["regen_count"]) == (
        False,
        db.REGEN_AUTO_MAX,
    )


def test_orphan_at_the_limit_has_no_mark_left_because_it_read_every_record(
    client: TestClient, pid: str
) -> None:
    vid = _generating_visit(client, pid)
    _set_regen_count(client, vid, db.REGEN_AUTO_MAX)
    assert _post(client, [_text(UUID_B, TEXT_B)]).status_code == 200
    assert _only_visit(client)["regen_pending"] is True
    settings = client.app.state.settings
    assert asyncio.run(orphans.recover_orphans(settings)) == 1
    only = _only_visit(client)
    assert (only["status"], only["fallback"]) == ("ready", True)
    assert (only["regen_pending"], only["regen_count"]) == (
        False,
        db.REGEN_AUTO_MAX,
    )


def test_record_arriving_during_recovery_is_read_without_using_a_run(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """周期の回収はリクエストを受けながら動く。途中で届いた記録も、枠を使わずに読み直す。"""
    vid = _generating_visit(client, pid)
    add = _add_from_other_phone(client, pid, _received(UUID_B, TEXT_B))
    real = service.generate_visit_report

    async def add_then_run(conn: sqlite3.Connection, visit_id: int, **kw: Any) -> None:
        add()
        await real(conn, visit_id, **kw)

    monkeypatch.setattr(service, "generate_visit_report", add_then_run)
    settings = client.app.state.settings
    assert asyncio.run(orphans.recover_orphans(settings)) == 1
    only = _only_visit(client)
    assert (only["status"], only["fallback"]) == ("ready", True)
    assert (only["regen_pending"], only["regen_count"]) == (False, 0)
    events = _events(client, vid)
    assert [e["event"] for e in events].count("run_start") == 2
    logged = [e for e in events if e["event"] == "regenerate_requested"]
    assert [e["decision"] for e in logged] == ["added_records"]


def _break_prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any) -> None:
        raise ValueError("入力を作れない")

    monkeypatch.setattr(service, "_prepare", broken)


def test_failed_regeneration_leaves_the_previous_report_usable_from_d3(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """別のスマホの送信で、印刷できていた紙が印刷できなくならない（§6「前のレポートは残り」）。"""
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    assert _row(client)["has_report"] is True
    _break_prepare(monkeypatch)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    row = _row(client)
    assert (row["status"], row["has_report"]) == ("failed", True)
    assert client.get(f"/api/doctor/visits/{row['id']}/report").status_code == 200
    assert client.post(f"/api/doctor/visits/{row['id']}/printed").status_code == 200
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []


def test_failed_first_generation_has_no_report(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_prepare(monkeypatch)
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    row = _row(client)
    assert (row["status"], row["has_report"]) == ("failed", False)
    assert client.get(f"/api/doctor/visits/{row['id']}/report").status_code == 404


def test_generating_row_does_not_offer_the_previous_report(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生成中は GET report が 404 を返すので、D3 の値もそれに揃える。"""
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200

    async def not_yet(*args: Any) -> None:
        return None

    monkeypatch.setattr(visit, "run_generation", not_yet)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    row = _row(client)
    assert (row["status"], row["has_report"]) == ("generating", False)

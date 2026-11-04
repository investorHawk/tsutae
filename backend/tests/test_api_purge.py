"""期限切れの受診の定期的な掃除（lifespan の周期タスク）。

- 起動中は `PURGE_INTERVAL_S` ごとに `purge_expired` を回す（医師 API を呼ばなくても
  24 時間を過ぎたレポート・変換結果・受付番号が消える）
- 終了時にタスクを止める。掃除の失敗は型名だけをログに残し、次の周期でまた試す
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from api_helpers import add_patient, api_client, db_conn

from tsutae import db
from tsutae.api import app as app_module
from tsutae.config import now, today

C1 = [(1, date(2026, 10, 27))]
WAIT_S = 5.0


def _wait_until(predicate, timeout: float = WAIT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _reception_no(app, vid: int) -> str | None:
    with db_conn(app) as conn:
        return db.get_visit(conn, vid)["reception_no"]


def test_periodic_purge_erases_expired_visits(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "PURGE_INTERVAL_S", 0.05)
    with api_client(tmp_path) as client:
        pid = add_patient(client.app, courses=C1)
        with db_conn(client.app) as conn:
            old = db.create_visit(
                conn, pid, "A-1", today(), now() - timedelta(minutes=1), 1
            )
            fresh = db.create_visit(
                conn, pid, "A-2", today(), now() + timedelta(hours=24), 1
            )
        assert _wait_until(lambda: _reception_no(client.app, old) is None)
        assert _reception_no(client.app, fresh) == "A-2"


def test_purge_task_stops_on_shutdown(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "PURGE_INTERVAL_S", 0.05)
    with api_client(tmp_path) as client:
        task = client.app.state.purge_task
        assert not task.done()
    assert task.done()


def test_purge_failure_is_logged_and_retried(
    tmp_path: Path,
    fixed_today: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(app_module, "PURGE_INTERVAL_S", 0.05)
    calls: list[int] = []
    real = app_module.purge_once

    def flaky(settings):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("secret text")
        return real(settings)

    with api_client(tmp_path):
        monkeypatch.setattr(app_module, "purge_once", flaky)
        assert _wait_until(lambda: len(calls) >= 2)
    assert "RuntimeError" in caplog.text
    assert "secret text" not in caplog.text


def test_purge_once_returns_count(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path) as client:
        pid = add_patient(client.app, courses=C1)
        with db_conn(client.app) as conn:
            db.create_visit(conn, pid, "A-1", today(), now() - timedelta(seconds=1), 1)
        assert app_module.purge_once(client.app.state.settings) == 1
        assert app_module.purge_once(client.app.state.settings) == 0

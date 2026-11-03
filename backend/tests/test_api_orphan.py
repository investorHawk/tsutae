"""起動時に、生成中のまま残った受診を AI 変換なしで救う（spec 6 のフォールバック）。

- 変換は同じプロセスの BackgroundTasks で動くので、変換中にサーバーが止まると受診は
  status=generating のまま残る。起動時（lifespan、purge の後・リクエストを受ける前）に
  1回だけ、受付番号が残っていて期限内の generating を全て、Claude を呼ばずに
  フォールバックのレポートにして ready（fallback=True）にする
- 印刷済み・期限切れ・ready には触れない。1件が壊れていても他は救い、壊れた1件は failed
- 起動後に作られた generating（同じプロセスで生成中）は奪わない
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import api_client, db_conn, make_settings

from tsutae import db
from tsutae.api import app as app_module
from tsutae.api import orphans
from tsutae.config import Settings, now, today
from tsutae.pipeline import service
from tsutae.schemas import ClosedAnswer, Course, EntryCreate

C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
FREE_TEXT = "おなかがゆるい日が続いた"
FALLBACK_MARK = "AI変換なし"


def _prepared_db(tmp_path: Path) -> tuple[Settings, Any]:
    settings = make_settings(tmp_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    return settings, conn


def _patient(conn: Any, courses=C3, free_text: str | None = FREE_TEXT) -> str:
    pid = db.create_patient(conn, "FOLFOX")
    for course_no, infusion in courses:
        db.upsert_course(
            conn, Course(patient_id=pid, course_no=course_no, infusion_date=infusion)
        )
    if free_text is not None:
        db.add_entry(
            conn, pid, EntryCreate(free_text=free_text), now(), "regimen-folfox@1"
        )
    return pid


def _visit(conn: Any, pid: str, reception_no: str, hours: float = 24) -> int:
    expires = now() + timedelta(hours=hours)
    return db.create_visit(conn, pid, reception_no, today(), expires, 3)


def _state(conn: Any, vid: int) -> tuple[Any, ...]:
    visit = db.get_visit(conn, vid)
    return (
        visit["status"],
        visit["fallback"],
        visit["reception_no"],
        db.get_report(conn, vid),
        db.get_timeline(conn, vid),
    )


def _events(conn: Any, vid: int) -> list[str]:
    return [e["event"] for e in db.list_pipeline_logs(conn, "visit", vid)]


def test_orphan_runner_always_fails() -> None:
    import asyncio

    runner = orphans.OrphanRunner()
    with pytest.raises(orphans.OrphanedVisitError):
        asyncio.run(runner.run("prompt", None, None))  # type: ignore[arg-type]


def test_generating_visit_is_recovered_as_fallback_without_claude(
    tmp_path: Path, fixed_today: str, caplog: pytest.LogCaptureFixture
) -> None:
    settings, conn = _prepared_db(tmp_path)
    pid = _patient(conn)
    vid = _visit(conn, pid, "A-023")
    conn.close()
    caplog.set_level(logging.INFO)
    with api_client(tmp_path, settings=settings) as client:
        factory = client.app.state.runner_factory
        with db_conn(client.app) as check:
            visit = db.get_visit(check, vid)
            report = db.get_report(check, vid)
            timeline = db.get_timeline(check, vid)
            events = _events(check, vid)
    assert visit["status"] == "ready"
    assert visit["fallback"] is True
    assert visit["reception_no"] == "A-023"
    assert report is not None
    html, data = report
    assert FALLBACK_MARK in html
    assert data.fallback is True
    assert timeline is not None
    assert factory.calls == 0
    assert factory.runner.calls == 0
    assert "orphan_recovered" in events
    assert "orphan_recovered" in caplog.text
    assert FREE_TEXT not in caplog.text
    assert "A-023" not in caplog.text


def test_closed_and_ready_visits_are_untouched(
    tmp_path: Path, fixed_today: str
) -> None:
    settings, conn = _prepared_db(tmp_path)
    pid = _patient(conn)
    printed = _visit(conn, pid, "P-1")
    db.mark_printed(conn, printed)
    expired = _visit(conn, pid, "E-1", hours=-1)
    ready = _visit(conn, pid, "R-1")
    db.set_visit_status(conn, ready, "ready", fallback=False)
    target = _visit(conn, pid, "G-1")
    before_printed = _state(conn, printed)
    before_ready = _state(conn, ready)
    conn.close()
    with api_client(tmp_path, settings=settings) as client:
        with db_conn(client.app) as check:
            assert _state(check, printed) == before_printed
            assert _state(check, ready) == before_ready
            status, _fb, reception_no, report, timeline = _state(check, expired)
            assert status == "generating"  # 期限切れは status を変えない
            assert (reception_no, report, timeline) == (None, None, None)
            for vid in (printed, expired, ready):
                assert "orphan_recovered" not in _events(check, vid)
            assert db.get_visit(check, target)["status"] == "ready"
        assert client.app.state.runner_factory.calls == 0


def test_broken_visit_fails_and_others_are_recovered(
    tmp_path: Path, fixed_today: str
) -> None:
    settings, conn = _prepared_db(tmp_path)
    no_course = _patient(conn, courses=[])
    broken = _visit(conn, no_course, "X-1")
    pid = _patient(conn)
    good = _visit(conn, pid, "A-1")
    conn.close()
    with (
        api_client(tmp_path, settings=settings) as client,
        db_conn(client.app) as check,
    ):
        assert db.get_visit(check, broken)["status"] == "failed"
        visit = db.get_visit(check, good)
        assert (visit["status"], visit["fallback"]) == ("ready", True)
        assert FALLBACK_MARK in db.get_report(check, good)[0]


def test_unexpected_exception_does_not_stop_others(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, conn = _prepared_db(tmp_path)
    pid = _patient(conn)
    first = _visit(conn, pid, "A-1")
    second = _visit(conn, pid, "A-2")
    conn.close()
    real = service.generate_visit_report

    async def flaky(conn, visit_id, *, runner, settings, logger=None):
        if visit_id == first:
            raise RuntimeError("患者の文面を含むかもしれない例外")
        return await real(conn, visit_id, runner=runner, settings=settings)

    monkeypatch.setattr(service, "generate_visit_report", flaky)
    with (
        api_client(tmp_path, settings=settings) as client,
        db_conn(client.app) as check,
    ):
        assert db.get_visit(check, first)["status"] == "failed"
        assert db.get_visit(check, second)["status"] == "ready"


def test_recovery_failure_does_not_stop_startup(
    tmp_path: Path,
    fixed_today: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken_find(conn):
        raise RuntimeError("secret text")

    monkeypatch.setattr(orphans, "find_orphans", broken_find)
    with api_client(tmp_path) as client:
        assert client.get("/api/patient/strings").status_code == 200
    assert "secret text" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_visit_without_free_text_is_ready_without_claude(
    tmp_path: Path, fixed_today: str
) -> None:
    """自由記載が無ければ AI は要らないので、通常と同じ（fallback=False）で ready。"""
    settings, conn = _prepared_db(tmp_path)
    pid = _patient(conn, free_text=None)
    db.add_entry(
        conn,
        pid,
        EntryCreate(answers=[ClosedAnswer(question_key="diarrhea", value="none")]),
        now(),
        "regimen-folfox@1",
    )
    vid = _visit(conn, pid, "A-1")
    conn.close()
    with api_client(tmp_path, settings=settings) as client:
        with db_conn(client.app) as check:
            visit = db.get_visit(check, vid)
        assert client.app.state.runner_factory.calls == 0
    assert (visit["status"], visit["fallback"]) == ("ready", False)


def test_visits_created_after_startup_are_not_taken(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回収は起動時の1回だけ（周期タスクに紛れ込まない）。"""
    monkeypatch.setattr(app_module, "PURGE_INTERVAL_S", 0.02)
    calls: list[int] = []
    real = app_module.purge_once

    def counting(settings):
        calls.append(1)
        return real(settings)

    monkeypatch.setattr(app_module, "purge_once", counting)
    with api_client(tmp_path) as client:
        with db_conn(client.app) as conn:
            pid = _patient(conn)
            vid = _visit(conn, pid, "A-1")
        start = len(calls)
        deadline = time.monotonic() + 5.0
        while len(calls) < start + 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(calls) >= start + 2  # 周期タスクが実際に回った
        with db_conn(client.app) as conn:
            assert _state(conn, vid)[:2] == ("generating", False)
            assert _events(conn, vid) == []
        assert client.app.state.runner_factory.calls == 0

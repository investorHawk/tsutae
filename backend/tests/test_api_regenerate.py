"""医師 API: `POST /api/doctor/visits/{id}/regenerate`（AI でもう一度変換）。

- 対象は受付番号が残っていて期限内の、failed か ready（fallback=True）の受診だけ
- それ以外（generating・AI の結果で ready・印刷済み・期限切れ）は 409 not_regenerable、
  無い受診は 404 not_found
- 受け付けたら generating にして、`POST /api/visit` と同じ `run_generation` を
  バックグラウンドで起動する（TestClient は応答の前に済ませる）
- ログに `regenerate_requested`（文面なし）
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import (
    RunnerFactory,
    add_entry,
    add_patient,
    api_client,
    db_conn,
    login_doctor,
    register,
    seed_synthetic,
)
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner, label_payloads, prepare_case, standard_steps

from tsutae import db
from tsutae.config import now
from tsutae.db.connection import dt_to_db
from tsutae.schemas import ClosedAnswer, EntryCreate

DEMO = "P-DEMO0001"
C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
NOT_REGENERABLE = {"error": "not_regenerable"}


def _scripted_runner() -> FakeRunner:
    """デモ患者の正解ラベルどおりに emit_* する runner（AI 変換ありの ready になる）。"""
    timeline, report = label_payloads("demo_patient", prepare_case("demo_patient"))
    return FakeRunner(standard_steps(timeline, report))


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    """台本なしの FakeRunner で起動（生成は fallback になる）。医師 Cookie つき。"""
    with api_client(tmp_path) as c:
        assert DEMO in seed_synthetic(c.app)
        login_doctor(c)
        yield c


def _use_runner(client: TestClient, runner: Any) -> RunnerFactory:
    factory = RunnerFactory(runner)
    client.app.state.runner_factory = factory
    return factory


def _url(vid: int) -> str:
    return f"/api/doctor/visits/{vid}/regenerate"


def _visit(client: TestClient, vid: int) -> dict[str, Any]:
    with db_conn(client.app) as conn:
        visit = db.get_visit(conn, vid)
    assert visit is not None
    return visit


def _events(client: TestClient, vid: int) -> list[str]:
    with db_conn(client.app) as conn:
        return [log["event"] for log in db.list_pipeline_logs(conn, "visit", vid)]


def _submit(client: TestClient, pid: str, reception_no: str = "A-023") -> int:
    """患者の受付（POST /api/visit）で受診を作り、生成を済ませた id を返す。"""
    register(client, pid)
    r = client.post("/api/visit", json={"reception_no": reception_no})
    assert r.status_code == 200
    with db_conn(client.app) as conn:
        return int(db.list_visits(conn)[-1]["id"])


def _demo_visit(client: TestClient, status: str | None = None) -> int:
    """デモ患者の受診を直接作る（generating。status があればその状態にする）。"""
    with db_conn(client.app) as conn:
        vid = db.create_visit(
            conn, DEMO, "A-023", date(2026, 11, 9), now() + timedelta(hours=24), 3
        )
        if status is not None:
            db.set_visit_status(conn, vid, status)
    return vid


# ---------------------------------------------------------------------------
# 受け付ける（failed・fallback の ready）
# ---------------------------------------------------------------------------


def test_failed_visit_is_regenerated_with_ai(client: TestClient) -> None:
    vid = _demo_visit(client, "failed")
    runner = _scripted_runner()
    factory = _use_runner(client, runner)
    r = client.post(_url(vid))
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert factory.calls == 1
    assert runner.calls == 1
    visit = _visit(client, vid)
    assert visit["status"] == "ready"
    assert visit["fallback"] is False
    with db_conn(client.app) as conn:
        assert db.get_report(conn, vid) is not None


def test_fallback_ready_visit_is_regenerated_with_ai(client: TestClient) -> None:
    vid = _submit(client, DEMO)  # 台本なしの runner → AI 変換なし
    before = _visit(client, vid)
    assert (before["status"], before["fallback"]) == ("ready", True)
    runner = _scripted_runner()
    _use_runner(client, runner)
    r = client.post(_url(vid))
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert runner.calls == 1
    after = _visit(client, vid)
    assert (after["status"], after["fallback"]) == ("ready", False)
    assert after["reception_no"] == "A-023"


def test_regenerate_logs_request_without_text(client: TestClient) -> None:
    vid = _demo_visit(client, "failed")
    _use_runner(client, _scripted_runner())
    assert client.post(_url(vid)).status_code == 200
    with db_conn(client.app) as conn:
        logs = db.list_pipeline_logs(conn, "visit", vid)
    requested = [log for log in logs if log["event"] == "regenerate_requested"]
    assert len(requested) == 1
    for key in ("hook_name", "agent_type", "tool_name", "decision"):
        assert requested[0][key] is None
    names = [log["event"] for log in logs]
    assert names.index("regenerate_requested") < names.index("run_start")


def test_regenerate_marks_generating_before_background(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """受け付けた時点で generating（生成は起動するだけ。終わりは一覧の取り直しで見る）。"""
    seen: list[tuple[int, str]] = []

    async def fake_run(settings: Any, runner_factory: Any, visit_id: int) -> None:
        seen.append((visit_id, _visit(client, visit_id)["status"]))

    from tsutae.api import doctor

    monkeypatch.setattr(doctor, "run_generation", fake_run)
    vid = _demo_visit(client, "failed")
    assert client.post(_url(vid)).status_code == 200
    assert seen == [(vid, "generating")]
    assert _visit(client, vid)["status"] == "generating"
    # 生成中に二重に押されたら 409
    r = client.post(_url(vid))
    assert r.status_code == 409
    assert r.json() == NOT_REGENERABLE
    assert len(seen) == 1


def test_failed_regeneration_falls_back_again(client: TestClient) -> None:
    """もう一度失敗しても（台本なし）、AI 変換なしのレポートで ready に戻る。"""
    vid = _demo_visit(client, "failed")
    runner = FakeRunner()
    _use_runner(client, runner)
    assert client.post(_url(vid)).status_code == 200
    assert runner.calls == 1
    visit = _visit(client, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", True)


# ---------------------------------------------------------------------------
# 断る（409・404・401・403）
# ---------------------------------------------------------------------------


def _assert_not_regenerable(client: TestClient, vid: int) -> dict[str, Any]:
    before = _visit(client, vid)
    runner = FakeRunner()
    factory = _use_runner(client, runner)
    r = client.post(_url(vid))
    assert r.status_code == 409
    assert r.json() == NOT_REGENERABLE
    assert factory.calls == 0
    assert runner.calls == 0
    after = _visit(client, vid)
    assert after == before
    assert "regenerate_requested" not in _events(client, vid)
    return after


def test_ai_ready_visit_is_409(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C3)
    entry = EntryCreate(answers=[ClosedAnswer(question_key="diarrhea", value="none")])
    add_entry(client.app, pid, entry)
    vid = _submit(client, pid, "A-024")  # 自由記載なし → AI の結果で ready
    assert _visit(client, vid)["fallback"] is False
    after = _assert_not_regenerable(client, vid)
    assert after["status"] == "ready"


def test_generating_visit_is_409(client: TestClient) -> None:
    vid = _demo_visit(client)
    assert _assert_not_regenerable(client, vid)["status"] == "generating"


def test_printed_visit_is_409(client: TestClient) -> None:
    vid = _demo_visit(client, "failed")
    with db_conn(client.app) as conn:
        db.mark_printed(conn, vid)
    after = _assert_not_regenerable(client, vid)
    assert after["status"] == "printed"
    assert after["reception_no"] is None


def test_printed_fallback_visit_is_409(client: TestClient) -> None:
    vid = _submit(client, DEMO)
    with db_conn(client.app) as conn:
        db.mark_printed(conn, vid)
    assert _assert_not_regenerable(client, vid)["status"] == "printed"


@pytest.mark.parametrize("status", ["failed", None])
def test_expired_visit_is_409(client: TestClient, status: str | None) -> None:
    """期限を過ぎた受診（purge の前でも）は 409。状態は変えない。"""
    vid = _demo_visit(client, status)
    past = dt_to_db(now() - timedelta(minutes=1))
    with db_conn(client.app) as conn, conn:
        conn.execute("UPDATE visits SET expires_at = ? WHERE id = ?", (past, vid))
    r = client.post(_url(vid))
    assert r.status_code == 409
    assert r.json() == NOT_REGENERABLE
    assert _visit(client, vid)["status"] == (status or "generating")


def test_expired_fallback_ready_visit_is_409(client: TestClient) -> None:
    vid = _submit(client, DEMO)
    past = dt_to_db(now() - timedelta(minutes=1))
    with db_conn(client.app) as conn, conn:
        conn.execute("UPDATE visits SET expires_at = ? WHERE id = ?", (past, vid))
    r = client.post(_url(vid))
    assert r.status_code == 409
    assert r.json() == NOT_REGENERABLE
    assert _visit(client, vid)["status"] == "ready"


def test_missing_visit_is_404(client: TestClient) -> None:
    r = client.post(_url(999))
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


def test_invalid_visit_id_is_422(client: TestClient) -> None:
    assert client.post("/api/doctor/visits/0/regenerate").status_code == 422


def test_without_doctor_cookie_is_401(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path) as c:
        assert DEMO in seed_synthetic(c.app)
        with db_conn(c.app) as conn:
            vid = db.create_visit(
                conn, DEMO, "A-023", date(2026, 11, 9), now() + timedelta(hours=24), 3
            )
            db.set_visit_status(conn, vid, "failed")
        r = c.post(_url(vid))
        assert r.status_code == 401
        assert r.json() == {"error": "not_logged_in"}
        with db_conn(c.app) as conn:
            assert db.get_visit(conn, vid)["status"] == "failed"


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}],
)
def test_cross_origin_is_403(client: TestClient, headers: dict[str, str]) -> None:
    vid = _demo_visit(client, "failed")
    factory = _use_runner(client, FakeRunner())
    r = client.post(_url(vid), headers=headers)
    assert r.status_code == 403
    assert r.json() == {"error": "cross_origin"}
    assert factory.calls == 0
    assert _visit(client, vid)["status"] == "failed"


def test_while_generating_old_report_is_hidden_and_cannot_be_printed(
    client: TestClient,
) -> None:
    # やり直しの最中（generating）に前のレポートを印刷して印刷済みにすると、新しい結果が
    # 捨てられる（Codex のレビュー）。レポートは 404、印刷済みは 409 にする
    vid = _demo_visit(client, "failed")
    with db_conn(client.app) as conn:
        assert db.begin_regeneration(conn, vid)
        conn.execute(
            "INSERT INTO reports (visit_id, html, data_json) VALUES (?, ?, ?)",
            (vid, "<p>old</p>", "{}"),
        )
        conn.commit()
    r = client.get(f"/api/doctor/visits/{vid}/report")
    assert r.status_code == 404
    r = client.post(f"/api/doctor/visits/{vid}/printed")
    assert r.status_code == 409
    assert r.json() == {"error": "generating"}
    assert _visit(client, vid)["status"] == "generating"

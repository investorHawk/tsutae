"""受診の受付 `POST /api/visit` とアプリの組み立て（docs/architecture.md §8b）。"""

from __future__ import annotations

import sqlite3
import sys
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
    make_app,
    make_settings,
    register,
    set_patient_cookie,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner

from tsutae import db
from tsutae.api import app as app_module
from tsutae.api.visit import normalize_reception_no
from tsutae.config import jst_datetime, now
from tsutae.pipeline import service
from tsutae.schemas import ClosedAnswer, EntryCreate, UnprocessedEntry

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
    register(client, patient_id)
    return patient_id


def _visits(client: TestClient) -> list[dict[str, Any]]:
    with db_conn(client.app) as conn:
        return db.list_visits(conn)


# ---------------------------------------------------------------------------
# 受付番号
# ---------------------------------------------------------------------------


def test_normalize_reception_no() -> None:
    assert normalize_reception_no("A-023") == "A-023"
    assert normalize_reception_no("　Ａ－０２３ ") == "A-023"
    assert normalize_reception_no("a-023") == "a-023"  # 大文字化しない
    assert normalize_reception_no("A‐023") == "A‐023"  # ハイフンの統一はしない
    assert normalize_reception_no("x" * 32) == "x" * 32
    assert normalize_reception_no("ｘ" * 32) == "x" * 32
    for bad in ("", "   ", "　", "x" * 33, "A\x00B", "A\nB", "A​B"):
        assert normalize_reception_no(bad) is None, repr(bad)


# ---------------------------------------------------------------------------
# エラー
# ---------------------------------------------------------------------------


def test_visit_without_cookie_is_401(client: TestClient) -> None:
    r = client.post("/api/visit", json={"reception_no": "A-023"})
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}
    assert _visits(client) == []


def test_visit_unknown_patient_is_404(client: TestClient) -> None:
    set_patient_cookie(client, "P-ZZZZZZZZ")
    r = client.post("/api/visit", json={"reception_no": "A-023"})
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_patient"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reception_no": ""},
        {"reception_no": "   "},
        {"reception_no": "x" * 33},
        {"reception_no": "x" * 300},
        {"reception_no": "A\x00B"},
        {"reception_no": 23},
        {"reception_no": "A-023", "pid": "P-AAAAAAAA"},
    ],
)
def test_visit_invalid_reception_is_422(
    client: TestClient, pid: str, body: dict
) -> None:
    r = client.post("/api/visit", json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}
    assert _visits(client) == []


def test_visit_without_current_course_is_409(client: TestClient) -> None:
    for courses in ([], [(1, date(2026, 11, 20))]):
        patient_id = add_patient(client.app, courses=courses)
        register(client, patient_id)
        r = client.post("/api/visit", json={"reception_no": "A-023"})
        assert r.status_code == 409
        assert r.json() == {"error": "no_course"}
    assert _visits(client) == []


# ---------------------------------------------------------------------------
# 作成とバックグラウンド生成（FakeRunner）
# ---------------------------------------------------------------------------


def test_visit_creates_and_generates_ready(
    client: TestClient, pid: str, runner: FakeRunner
) -> None:
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    before = now()
    r = client.post("/api/visit", json={"reception_no": "　Ａ－０２３ "})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message_key": "visit.done"}
    (visit,) = _visits(client)
    assert visit["patient_id"] == pid
    assert visit["reception_no"] == "A-023"
    assert visit["visit_date"] == date(2026, 11, 9)
    assert visit["course_no"] == 3
    ttl = visit["expires_at"] - before
    assert timedelta(hours=24) <= ttl < timedelta(hours=24, minutes=1)
    # TestClient はバックグラウンドの完了まで待つ
    assert visit["status"] == "ready"
    assert visit["fallback"] is True  # 台本なし → emit_timeline が来ない → AI変換なし
    assert runner.calls == 1
    assert all("A-023" not in p and pid not in p for p in runner.prompts)
    with db_conn(client.app) as conn:
        report = db.get_report(conn, visit["id"])
        assert report is not None
        assert db.get_timeline(conn, visit["id"]) is not None


def _to_fullwidth(text: str) -> str:
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text)


@pytest.mark.parametrize("reception_no", ["A-023", "カエデ305"])
def test_identifiers_in_free_text_never_reach_prompt(
    client: TestClient, pid: str, runner: FakeRunner, reception_no: str
) -> None:
    """仮名ID・受付番号を書いた記録は Claude に送らず known_identifier で外す。"""
    clean = add_entry(
        client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた")
    )
    with_pid = add_entry(
        client.app, pid, EntryCreate(free_text=f"紙に{pid}と書いてあった")
    )
    with_wide_pid = add_entry(
        client.app, pid, EntryCreate(free_text=f"控えは{_to_fullwidth(pid)}だった")
    )
    with_reception = add_entry(
        client.app, pid, EntryCreate(free_text=f"受付票は{reception_no}だった")
    )
    r = client.post("/api/visit", json={"reception_no": reception_no})
    assert r.status_code == 200
    (visit,) = _visits(client)
    assert visit["status"] == "ready"
    assert runner.calls == 1  # 外れない記録があるので Claude は呼ばれる
    (prompt,) = runner.prompts
    assert "おなかがゆるい" in prompt
    for leaked in (pid, pid.lower(), _to_fullwidth(pid), reception_no):
        assert leaked not in prompt, leaked
    for marker in ("紙に", "控えは", "受付票は"):
        assert marker not in prompt, marker
    with db_conn(client.app) as conn:
        timeline = db.get_timeline(conn, visit["id"])
    assert timeline is not None
    assert sorted(timeline.unprocessed_entries, key=lambda u: u.entry_id) == [
        UnprocessedEntry(entry_id=eid, reason="known_identifier")
        for eid in (with_pid, with_wide_pid, with_reception)
    ]
    assert clean not in {u.entry_id for u in timeline.unprocessed_entries}


def test_visit_without_free_text_is_ready_without_claude(
    client: TestClient, pid: str, runner: FakeRunner
) -> None:
    entry = EntryCreate(answers=[ClosedAnswer(question_key="diarrhea", value="none")])
    add_entry(client.app, pid, entry)
    assert client.post("/api/visit", json={"reception_no": "A-024"}).status_code == 200
    (visit,) = _visits(client)
    assert visit["status"] == "ready"
    assert visit["fallback"] is False
    assert runner.calls == 0


def test_background_uses_new_connection_and_factory_runner(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_generate(conn, visit_id, *, runner, settings, logger=None):
        assert isinstance(conn, sqlite3.Connection)
        assert conn.execute("SELECT status FROM visits WHERE id = ?", (visit_id,))
        calls.append(
            {"conn": conn, "visit_id": visit_id, "runner": runner, "settings": settings}
        )

    monkeypatch.setattr(service, "generate_visit_report", fake_generate)
    sentinel_runner = object()
    app = make_app(tmp_path, runner=sentinel_runner)
    with TestClient(app) as c:
        patient_id = add_patient(c.app, courses=C3)
        register(c, patient_id)
        assert c.post("/api/visit", json={"reception_no": "A-1"}).status_code == 200
    (visit,) = [v for v in _visits_of(app)]
    assert len(calls) == 1
    assert calls[0]["visit_id"] == visit["id"]
    assert calls[0]["runner"] is sentinel_runner
    assert calls[0]["settings"] is app.state.settings
    factory = app.state.runner_factory
    assert isinstance(factory, RunnerFactory) and factory.calls == 1
    with pytest.raises(sqlite3.ProgrammingError):  # 終わったら閉じている
        calls[0]["conn"].execute("SELECT 1")
    assert visit["status"] == "generating"  # 偽の生成は状態を変えない


def _visits_of(app: FastAPI) -> list[dict[str, Any]]:
    with db_conn(app) as conn:
        return db.list_visits(conn)


def test_background_failure_marks_failed_and_still_200(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(conn, visit_id, *, runner, settings, logger=None):
        raise RuntimeError("患者の文面を含むかもしれない例外")

    monkeypatch.setattr(service, "generate_visit_report", boom)
    with api_client(tmp_path) as c:
        patient_id = add_patient(c.app, courses=C3)
        register(c, patient_id)
        r = c.post("/api/visit", json={"reception_no": "A-2"})
        assert r.status_code == 200
        (visit,) = _visits(c)
    assert visit["status"] == "failed"


def test_background_runner_factory_failure_marks_failed(
    tmp_path: Path, fixed_today: str
) -> None:
    def broken_factory() -> Any:
        raise RuntimeError("no runner")

    app = make_app(tmp_path)
    app.state.runner_factory = broken_factory
    with TestClient(app) as c:
        patient_id = add_patient(c.app, courses=C3)
        register(c, patient_id)
        assert c.post("/api/visit", json={"reception_no": "A-3"}).status_code == 200
        (visit,) = _visits(c)
    assert visit["status"] == "failed"


# ---------------------------------------------------------------------------
# アプリの組み立て（起動処理・既定値・任意のルーター）
# ---------------------------------------------------------------------------


def test_startup_inits_db_registers_skills_and_purges(
    tmp_path: Path, fixed_today: str
) -> None:
    settings = make_settings(tmp_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    pid = db.create_patient(conn, "FOLFOX")
    old = db.create_visit(
        conn, pid, "A-9", date(2026, 11, 1), jst_datetime(date(2026, 11, 2), 9), 1
    )
    conn.close()
    with api_client(tmp_path, settings=settings) as c, db_conn(c.app) as check:
        assert db.get_visit(check, old)["reception_no"] is None
        assert db.latest_skill_version(check, "regimen-folfox") is not None
        assert db.latest_skill_version(check, "regimen-capox") is not None


def test_create_app_state(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = app_module.create_app(settings, skill_editor="editor")
    assert app.state.settings is settings
    assert app.state.runner_factory is app_module.SdkRunner
    assert app.state.skill_editor == "editor"
    assert app.state.skills_home == settings.skills_dir.parent.parent
    assert (app.state.skills_home / ".claude" / "skills") == settings.skills_dir


def test_module_app_is_lazy() -> None:
    assert "_app" in vars(app_module)
    with pytest.raises(AttributeError):
        app_module.no_such_attribute  # noqa: B018


def _write_module(root: Path, name: str, body: str) -> None:
    pkg = root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(body, encoding="utf-8")


def test_optional_router_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_module(
        tmp_path,
        "tsutae_fake_router_ok",
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/api/fake-ok')\n"
        "def ok():\n    return {'ok': True}\n",
    )
    _write_module(
        tmp_path, "tsutae_fake_router_broken", "import tsutae_no_such_dependency_x\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    app = FastAPI()
    assert app_module._include_optional(app, "tsutae_fake_router_missing") is False
    assert app_module._include_optional(app, "tsutae_fake_router_ok") is True
    assert TestClient(app).get("/api/fake-ok").json() == {"ok": True}
    with pytest.raises(ModuleNotFoundError):  # 中の import の失敗は隠さない
        app_module._include_optional(app, "tsutae_fake_router_broken")
    for name in ("tsutae_fake_router_ok", "tsutae_fake_router_broken"):
        sys.modules.pop(name, None)


def test_default_skill_editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    monkeypatch.setattr(app_module, "SKILLCHANGE_MODULE", "tsutae_no_skillchange_x")
    assert app_module._default_skill_editor(settings) is None
    _write_module(
        tmp_path,
        "tsutae_fake_skillchange",
        "class SdkSkillEditor:\n"
        "    def __init__(self, settings=None):\n"
        "        self.settings = settings\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(app_module, "SKILLCHANGE_MODULE", "tsutae_fake_skillchange")
    editor = app_module._default_skill_editor(settings)
    assert editor.settings is settings
    sys.modules.pop("tsutae_fake_skillchange", None)


# ---------------------------------------------------------------------------
# デモの流れ（合成データを投入 → 受付 → FakeRunner で AI 変換ありの ready）
# ---------------------------------------------------------------------------


def test_demo_patient_visit_ready_with_scripted_runner(
    tmp_path: Path, fixed_today: str
) -> None:
    from api_helpers import seed_synthetic
    from pipeline_fakes import label_payloads, prepare_case, standard_steps

    prepared = prepare_case("demo_patient")
    timeline, report = label_payloads("demo_patient", prepared)
    runner = FakeRunner(standard_steps(timeline, report))
    with api_client(tmp_path, runner=runner) as c:
        assert "P-DEMO0001" in seed_synthetic(c.app)
        register(c, "P-DEMO0001")
        r = c.post("/api/visit", json={"reception_no": "A-023"})
        assert r.status_code == 200
        (visit,) = _visits(c)
        with db_conn(c.app) as conn:
            saved = db.get_timeline(conn, visit["id"])
    assert runner.denied() == []
    assert visit["course_no"] == 3
    assert visit["status"] == "ready"
    assert visit["fallback"] is False
    assert saved is not None and saved.events
    assert len(saved.unprocessed_entries) == 1  # 二次検出に掛かる記載（D6 デモ用）

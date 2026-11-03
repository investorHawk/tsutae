"""フロントの契約テスト用に、今の FastAPI の応答を fixture に書き出す。症例は全て合成。

    .venv/bin/python scripts/dump_api_fixtures.py [--out DIR]

- 一時ディレクトリの DB に合成3人（`tsutae.dataset`）を入れ、`create_app`（偽の runner・
  偽の editor。Anthropic API は呼ばない）を TestClient で叩く。患者 API・医師 API の
  全経路（成功と代表的な失敗）の応答を `frontend/src/test/fixtures/api/<名前>.json` に書く
- 1件は `{method, path, request, status, body}`。失敗の body は `{"error": code}`
- 日時は固定する: `TSUTAE_TODAY=2026-11-09` と、`tsutae.config` の時計を
  2026-11-09T10:00:00+09:00 に止める（`now()` を名前で import した全モジュールに効く）。
  新しい患者の仮名IDも固定する。同じコードなら何度流しても同じ fixture になる
- Skill は `backend/skills_home` を一時ディレクトリに写して使う（本物を書き換えない）
- `backend/tests/test_dump_api_fixtures.py` が、書いた fixture が今の API の出力と
  一致すること（古くなっていないこと）を確かめる。API を変えたらこれを流し直す
- テスト用の偽物（`backend/tests/api_helpers.py`・`pipeline_fakes.py`）を使う
- 印刷の経路 `GET /api/doctor/visits/{id}/report`（text/html）は JSON の fixture とは別枠:
  ready の受診で 200・text/html・`Cache-Control: no-store`・CSP（§8b の値）、未認証は
  401 not_logged_in、無い・生成中・印刷済みの受診は 404 not_found を確かめ、違えば
  `DumpError` で止める（`build_dump(...).report_checks` に結果の要約を残す）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "backend" / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import httpx  # noqa: E402
from api_helpers import (  # noqa: E402
    db_conn,
    make_app,
    make_settings,
    seed_synthetic,
    set_patient_cookie,
)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pipeline_fakes import (  # noqa: E402
    FakeRunner,
    label_payloads,
    prepare_case,
    standard_steps,
)

from tsutae import db  # noqa: E402
from tsutae.config import JST, SKILLS_HOME  # noqa: E402
from tsutae.schemas import RunStats  # noqa: E402
from tsutae.skillchange.lock import skill_lock  # noqa: E402

__all__ = [
    "FIXED_NOW",
    "FIXED_TODAY",
    "JSON_ROUTES",
    "OUT_DIR",
    "REPORT_CACHE_CONTROL",
    "REPORT_CSP",
    "REPORT_HTML_ROUTE",
    "Dump",
    "DumpError",
    "app_json_routes",
    "app_routes",
    "build_dump",
    "build_fixtures",
    "check_report_error",
    "check_report_html",
    "main",
    "render",
    "route_template",
    "write_fixtures",
]

OUT_DIR = REPO_ROOT / "frontend" / "src" / "test" / "fixtures" / "api"
FIXED_TODAY = "2026-11-09"
FIXED_NOW = datetime(2026, 11, 9, 10, 0, 0, tzinfo=JST)
PUBLIC_BASE_URL = "http://localhost:5173"
DEMO = "P-DEMO0001"
EVAL_A = "P-EVAL0001"
EVAL_B = "P-EVAL0002"
UNKNOWN = "P-ZZZZ9999"
NO_COURSE = "P-NOCOURSE"
NEW_PATIENT = "P-FIXT0001"
MISSING_ID = 999
REGIMEN_SKILL = "regimen-folfox"
REPORT_SKILL = "report-format-default"
NO_CHANGE_REQUEST = "今のままでよい"
REPORT_HTML_ROUTE = ("GET", "/api/doctor/visits/{}/report")
# §8b の契約の値（バックエンドの定数ではなく契約の文字列と比べる）
REPORT_CACHE_CONTROL = "no-store"
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"

# §8 の JSON の経路（`route_template` の形）。レポート（text/html）は除く
JSON_ROUTES = frozenset(
    {
        ("POST", "/api/patient/register"),
        ("GET", "/api/patient/strings"),
        ("GET", "/api/patient/{}/questions"),
        ("POST", "/api/patient/{}/entries"),
        ("GET", "/api/patient/{}/entries"),
        ("POST", "/api/visit"),
        ("POST", "/api/doctor/login"),
        ("POST", "/api/doctor/logout"),
        ("GET", "/api/doctor/patients"),
        ("POST", "/api/doctor/patients"),
        ("GET", "/api/doctor/patients/{}/courses"),
        ("POST", "/api/doctor/courses"),
        ("GET", "/api/doctor/visits"),
        ("POST", "/api/doctor/visits/{}/printed"),
        ("POST", "/api/doctor/visits/{}/regenerate"),
        ("GET", "/api/doctor/visits/{}/unprocessed"),
        ("GET", "/api/doctor/pipeline/{}/events"),
        ("GET", "/api/doctor/skills"),
        ("POST", "/api/doctor/skill-changes"),
        ("GET", "/api/doctor/skill-changes"),
        ("POST", "/api/doctor/skill-changes/{}/approve"),
        ("POST", "/api/doctor/skill-changes/{}/reject"),
    }
)

_PID_SEGMENT = re.compile(r"/P-[A-Z0-9]{8}(?=/|$)")
_INT_SEGMENT = re.compile(r"/[0-9]+(?=/|$)")
_PARAM_SEGMENT = re.compile(r"/\{[^/}]+\}(?=/|$)")


class DumpError(RuntimeError):
    """台本どおりの応答にならなかった（API が変わった）。"""


def route_template(path: str) -> str:
    """`/api/patient/P-DEMO0001/entries` → `/api/patient/{}/entries`（id も `{}`）。"""
    return _INT_SEGMENT.sub("/{}", _PID_SEGMENT.sub("/{}", path))


def app_routes(app: FastAPI) -> set[tuple[str, str]]:
    """アプリに載っている全経路（`route_template` の形。レポートの HTML を含む）。

    `app.openapi()` の paths から作る（`/openapi.json` の公開とは別。メモリ上で作るだけ）。
    """
    paths: dict[str, dict[str, Any]] = app.openapi().get("paths", {})
    return {
        (method.upper(), _PARAM_SEGMENT.sub("/{}", path))
        for path, operations in paths.items()
        for method in operations
    }


def app_json_routes(app: FastAPI) -> set[tuple[str, str]]:
    """アプリに載っている JSON の経路。レポートの HTML は除く（別枠で検査する）。"""
    return app_routes(app) - {REPORT_HTML_ROUTE}


# ---------------------------------------------------------------------------
# 時計・仮名ID・Skill の固定
# ---------------------------------------------------------------------------


class _FrozenClock:
    """`tsutae.config` の `datetime` の代わり。`now()` だけ FIXED_NOW、他は本物。"""

    def __getattr__(self, name: str) -> Any:
        return getattr(datetime, name)

    @staticmethod
    def now(tz: Any = None) -> datetime:
        if tz is None:
            return FIXED_NOW.replace(tzinfo=None)
        return FIXED_NOW.astimezone(tz)


@contextmanager
def _fixed_world() -> Iterator[None]:
    """今日・時計・新しい仮名ID・Skill のロック待ちを固定する（終われば元に戻す）。"""
    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, {"TSUTAE_TODAY": FIXED_TODAY}))
        stack.enter_context(mock.patch("tsutae.config.datetime", _FrozenClock()))
        # 固定日の時計の起点を、止めた時計で取り直す（実時計で取った起点を使わない）
        stack.enter_context(mock.patch("tsutae.config._FIXED_ANCHORS", {}))
        stack.enter_context(
            mock.patch(
                "tsutae.db.repo_patients._new_patient_id", return_value=NEW_PATIENT
            )
        )
        stack.enter_context(mock.patch("tsutae.skillchange.lock.LOCK_TIMEOUT_S", 0.0))
        yield


def _copy_skills_home(work_dir: Path) -> Path:
    home = work_dir / "skills_home"
    shutil.copytree(SKILLS_HOME, home, ignore=shutil.ignore_patterns("__pycache__"))
    return home


def _skill_dir(home: Path, name: str) -> Path:
    return home / ".claude" / "skills" / name


@dataclass
class ScriptedEditor:
    """SkillEditor の偽物。本文の末尾に1行足す（NO_CHANGE_REQUEST なら何もしない）。"""

    calls: list[str] = field(default_factory=list)

    async def edit(
        self, work_root: Path, skill_name: str, request_text: str
    ) -> RunStats:
        self.calls.append(skill_name)
        if request_text != NO_CHANGE_REQUEST:
            path = _skill_dir(Path(work_root), skill_name) / "SKILL.md"
            text = path.read_text(encoding="utf-8").rstrip("\n")
            path.write_text(f"{text}\n- 依頼: {request_text}\n", encoding="utf-8")
        return RunStats(duration_ms=1000, num_turns=2)


def _demo_runner() -> FakeRunner:
    """デモ患者の正解ラベルどおりに emit_* する runner（AI 変換ありの ready になる）。"""
    timeline, report = label_payloads("demo_patient", prepare_case("demo_patient"))
    return FakeRunner(standard_steps(timeline, report))


# ---------------------------------------------------------------------------
# 応答の記録
# ---------------------------------------------------------------------------


@dataclass
class Recorder:
    client: TestClient
    fixtures: dict[str, dict[str, Any]] = field(default_factory=dict)
    report_checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def call(
        self,
        name: str,
        method: str,
        path: str,
        body: Any = None,
        *,
        expect: int = 200,
    ) -> Any:
        """1回呼び、`{method, path, request, status, body}` を name で残す。"""
        if name in self.fixtures:
            raise DumpError(f"{name}: 名前が重複")
        response = self.client.request(method, path, json=body)
        if response.status_code != expect:
            raise DumpError(f"{name}: status {response.status_code} != {expect}")
        data = response.json()
        self.fixtures[name] = {
            "method": method,
            "path": path,
            "request": body,
            "status": response.status_code,
            "body": data,
        }
        return data

    @contextmanager
    def without_cookies(self) -> Iterator[None]:
        saved = dict(self.client.cookies.items())
        self.client.cookies.clear()
        try:
            yield
        finally:
            for key, value in saved.items():
                self.client.cookies.set(key, value)


# ---------------------------------------------------------------------------
# 印刷の経路（text/html。JSON の fixture とは別枠）
# ---------------------------------------------------------------------------


def check_report_html(name: str, response: httpx.Response) -> dict[str, Any]:
    """レポートの成功の応答が §8b の形か。違えば DumpError。要約（本文なし）を返す。"""
    headers = response.headers
    content_type = headers.get("content-type", "")
    summary = {
        "status": response.status_code,
        "content_type": content_type,
        "cache_control": headers.get("cache-control"),
        "content_security_policy": headers.get("content-security-policy"),
        "doctype": response.text.lstrip().lower().startswith("<!doctype html"),
    }
    problems = [
        label
        for label, ok in (
            ("status", response.status_code == 200),
            ("content-type", content_type.split(";")[0].strip() == "text/html"),
            ("cache-control", summary["cache_control"] == REPORT_CACHE_CONTROL),
            ("csp", summary["content_security_policy"] == REPORT_CSP),
            ("doctype", summary["doctype"]),
        )
        if not ok
    ]
    if problems:
        raise DumpError(f"{name}: レポートの応答が契約と違う {problems}")
    return summary


def check_report_error(
    name: str, response: httpx.Response, status: int, code: str
) -> dict[str, Any]:
    """レポートの失敗が `status` の `{"error": code}`（JSON）か。違えば DumpError。"""
    try:
        body = response.json()
    except ValueError as exc:
        raise DumpError(f"{name}: 失敗の本文が JSON でない") from exc
    summary = {"status": response.status_code, "error": None}
    if isinstance(body, dict) and set(body) == {"error"}:
        summary["error"] = body["error"]
    if summary != {"status": status, "error": code}:
        raise DumpError(f"{name}: {summary} != {status} {code}")
    return summary


def _report_path(visit_id: int) -> str:
    return f"/api/doctor/visits/{visit_id}/report"


def _check_open_reports(rec: Recorder, ready: int, generating: int) -> None:
    """印刷前: ready は HTML、未認証は 401、無い・生成中の受診は 404。"""
    get = rec.client.get
    rec.report_checks["ready"] = check_report_html("ready", get(_report_path(ready)))
    with rec.without_cookies():
        rec.report_checks["not_logged_in"] = check_report_error(
            "not_logged_in", get(_report_path(ready)), 401, "not_logged_in"
        )
    for name, vid in (("not_found", MISSING_ID), ("generating", generating)):
        rec.report_checks[name] = check_report_error(
            name, get(_report_path(vid)), 404, "not_found"
        )


def _check_printed_report(rec: Recorder, printed: int) -> None:
    """印刷済みの受診のレポートは消えている（404）。"""
    rec.report_checks["printed"] = check_report_error(
        "printed", rec.client.get(_report_path(printed)), 404, "not_found"
    )


# ---------------------------------------------------------------------------
# 台本（順序に意味がある。id は呼んだ順に振られる）
# ---------------------------------------------------------------------------


def _patient_flow(rec: Recorder) -> None:
    rec.call(
        "patient_register_unknown",
        "POST",
        "/api/patient/register",
        {"pid": UNKNOWN},
        expect=404,
    )
    rec.call("patient_register", "POST", "/api/patient/register", {"pid": DEMO})
    rec.call("patient_strings", "GET", "/api/patient/strings")
    rec.call("patient_questions", "GET", f"/api/patient/{DEMO}/questions")
    rec.call(
        "patient_questions_forbidden",
        "GET",
        f"/api/patient/{EVAL_A}/questions",
        expect=403,
    )
    # 受付（変換はバックグラウンド。TestClient は応答の前に済ませる）
    rec.call("visit", "POST", "/api/visit", {"reception_no": "A-023"})
    rec.call("visit_invalid", "POST", "/api/visit", {"reception_no": "   "}, expect=422)
    entry = {
        "by_proxy": False,
        "answers": [
            {"question_key": "fever", "value": "measured", "temperature": 38.2},
            {"question_key": "diarrhea", "value": "present", "temperature": None},
        ],
        "free_text": None,
    }
    rec.call("patient_entry_create", "POST", f"/api/patient/{DEMO}/entries", entry)
    bad = {"answers": [{"question_key": "unknown_question", "value": "none"}]}
    rec.call(
        "patient_entry_create_invalid",
        "POST",
        f"/api/patient/{DEMO}/entries",
        bad,
        expect=422,
    )
    rec.call("patient_entries", "GET", f"/api/patient/{DEMO}/entries")
    with rec.without_cookies():
        rec.call(
            "patient_entries_not_logged_in",
            "GET",
            f"/api/patient/{DEMO}/entries",
            expect=401,
        )
    set_patient_cookie(rec.client, NO_COURSE)
    rec.call(
        "visit_no_course", "POST", "/api/visit", {"reception_no": "B-7"}, expect=409
    )
    set_patient_cookie(rec.client, DEMO)


def _add_open_visits(app: FastAPI) -> tuple[int, int]:
    """生成中（評価A）と失敗（評価B）の受診を直接作る（runner はデモ患者用の1つだけ）。"""
    expires = FIXED_NOW + timedelta(hours=24)
    visit_date = FIXED_NOW.date()
    with db_conn(app) as conn:
        generating = db.create_visit(conn, EVAL_A, "B-101", visit_date, expires, 2)
        failed = db.create_visit(conn, EVAL_B, "C-202", visit_date, expires, 2)
        db.set_visit_status(conn, failed, "failed")
    return generating, failed


def _ready_visit_id(app: FastAPI) -> int:
    with db_conn(app) as conn:
        ready = [v for v in db.list_visits(conn) if v["patient_id"] == DEMO]
    if len(ready) != 1 or ready[0]["status"] != "ready":
        raise DumpError("デモ患者の受診が ready になっていない")
    return int(ready[0]["id"])


def _doctor_session(rec: Recorder) -> None:
    password = rec.client.app.state.settings.doctor_password
    with rec.without_cookies():
        rec.call("doctor_visits_not_logged_in", "GET", "/api/doctor/visits", expect=401)
    rec.call(
        "doctor_login_rejected",
        "POST",
        "/api/doctor/login",
        {"password": "wrong-password"},
        expect=401,
    )
    rec.call("doctor_login", "POST", "/api/doctor/login", {"password": password})


def _visit_flow(rec: Recorder) -> None:
    app = rec.client.app
    ready = _ready_visit_id(app)
    generating, failed = _add_open_visits(app)
    _check_open_reports(rec, ready, generating)
    rec.call("doctor_visits", "GET", "/api/doctor/visits")
    rec.call("doctor_unprocessed", "GET", f"/api/doctor/visits/{ready}/unprocessed")
    rec.call(
        "doctor_unprocessed_not_found",
        "GET",
        f"/api/doctor/visits/{MISSING_ID}/unprocessed",
        expect=404,
    )
    rec.call("doctor_pipeline_events", "GET", f"/api/doctor/pipeline/{ready}/events")
    rec.call(
        "doctor_pipeline_events_generating",
        "GET",
        f"/api/doctor/pipeline/{generating}/events",
    )
    rec.call(
        "doctor_pipeline_events_not_found",
        "GET",
        f"/api/doctor/pipeline/{MISSING_ID}/events",
        expect=404,
    )
    rec.call("doctor_printed", "POST", f"/api/doctor/visits/{ready}/printed")
    rec.call(
        "doctor_printed_not_found",
        "POST",
        f"/api/doctor/visits/{MISSING_ID}/printed",
        expect=404,
    )
    _check_printed_report(rec, ready)
    rec.call("doctor_visits_after_printed", "GET", "/api/doctor/visits")
    rec.call(
        "doctor_pipeline_events_printed", "GET", f"/api/doctor/pipeline/{ready}/events"
    )
    _regenerate_flow(rec, generating, failed)


def _regenerate_flow(rec: Recorder, generating: int, failed: int) -> None:
    """AI でもう一度変換: 失敗の受診は受け付け、生成中・無い受診は断る。

    一覧の fixture（doctor_visits）を変えないよう、一覧を取った後に流す。
    """
    base = "/api/doctor/visits"
    rec.call("doctor_regenerate", "POST", f"{base}/{failed}/regenerate")
    rec.call(
        "doctor_regenerate_not_regenerable",
        "POST",
        f"{base}/{generating}/regenerate",
        expect=409,
    )
    rec.call(
        "doctor_regenerate_not_found",
        "POST",
        f"{base}/{MISSING_ID}/regenerate",
        expect=404,
    )


def _patient_admin_flow(rec: Recorder) -> None:
    rec.call("doctor_patients", "GET", "/api/doctor/patients")
    rec.call(
        "doctor_patient_create", "POST", "/api/doctor/patients", {"regimen": "CAPOX"}
    )
    rec.call("doctor_courses", "GET", f"/api/doctor/patients/{DEMO}/courses")
    rec.call(
        "doctor_courses_unknown_patient",
        "GET",
        f"/api/doctor/patients/{UNKNOWN}/courses",
        expect=404,
    )
    course = {
        "patient_id": NEW_PATIENT,
        "course_no": 1,
        "infusion_date": "2026-11-09",
        "planned_date": "2026-11-09",
        "next_visit": "2026-11-30",
        "note": None,
    }
    rec.call("doctor_course_save", "POST", "/api/doctor/courses", course)
    earlier = {"patient_id": NEW_PATIENT, "course_no": 2, "infusion_date": "2026-11-01"}
    rec.call(
        "doctor_course_save_invalid", "POST", "/api/doctor/courses", earlier, expect=400
    )


def _request_change(rec: Recorder, name: str | None, skill: str, text: str) -> int:
    body = {"skill_name": skill, "request_text": text}
    if name is None:
        response = rec.client.post("/api/doctor/skill-changes", json=body)
        if response.status_code != 200:
            raise DumpError(f"skill-change: status {response.status_code}")
        return int(response.json()["id"])
    return int(rec.call(name, "POST", "/api/doctor/skill-changes", body)["id"])


def _skill_flow(rec: Recorder, home: Path) -> None:
    base = "/api/doctor/skill-changes"
    rec.call("doctor_skills", "GET", "/api/doctor/skills")
    first = _request_change(
        rec,
        "doctor_skill_change_create",
        REGIMEN_SKILL,
        "口内炎の質問で食事がとれたかも聞いて",
    )
    _request_change(
        rec, "doctor_skill_change_create_failed", REGIMEN_SKILL, NO_CHANGE_REQUEST
    )
    rec.call(
        "doctor_skill_change_create_invalid_name",
        "POST",
        base,
        {"skill_name": "../etc", "request_text": "x"},
        expect=400,
    )
    second = _request_change(rec, None, REPORT_SKILL, "引用は短くして")
    with skill_lock(_skill_dir(home, REGIMEN_SKILL)):
        rec.call(
            "doctor_skill_change_approve_busy",
            "POST",
            f"{base}/{first}/approve",
            expect=409,
        )
    with skill_lock(_skill_dir(home, REPORT_SKILL)):
        rec.call(
            "doctor_skill_change_reject_busy",
            "POST",
            f"{base}/{second}/reject",
            expect=409,
        )
    rec.call("doctor_skill_change_approve", "POST", f"{base}/{first}/approve")
    rec.call(
        "doctor_skill_change_approve_not_pending",
        "POST",
        f"{base}/{first}/approve",
        expect=409,
    )
    rec.call("doctor_skill_change_reject", "POST", f"{base}/{second}/reject")
    rec.call("doctor_skill_changes", "GET", base)
    _skills_with_invalid(rec, home)


def _skills_with_invalid(rec: Recorder, home: Path) -> None:
    """壊れた任意の Skill を1つ置いて一覧を取る（必須の Skill は壊さない）。"""
    extra = _skill_dir(home, "regimen-extra")
    extra.mkdir()
    (extra / "SKILL.md").write_text("---\nname: regimen-extra\n---\n本文\n", "utf-8")
    try:
        rec.call("doctor_skills_invalid", "GET", "/api/doctor/skills")
    finally:
        shutil.rmtree(extra)


@dataclass(frozen=True)
class Dump:
    """1回の生成の結果。fixtures は JSON の経路、report_checks は印刷の経路の要約。"""

    fixtures: dict[str, dict[str, Any]]
    report_checks: dict[str, dict[str, Any]]


def _run(app: FastAPI, home: Path) -> Dump:
    with TestClient(app) as client:
        if DEMO not in seed_synthetic(app):
            raise DumpError("デモ患者を入れられない")
        with db_conn(app) as conn:
            db.create_patient(conn, "FOLFOX", patient_id=NO_COURSE)
        rec = Recorder(client)
        _patient_flow(rec)
        _doctor_session(rec)
        _visit_flow(rec)
        _patient_admin_flow(rec)
        _skill_flow(rec, home)
        rec.call("doctor_logout", "POST", "/api/doctor/logout")
        return Dump(
            fixtures=dict(sorted(rec.fixtures.items())),
            report_checks=dict(sorted(rec.report_checks.items())),
        )


def build_fixtures(work_dir: Path) -> dict[str, dict[str, Any]]:
    """work_dir（空のディレクトリ）に DB と Skill の写しを作り、全 fixture を返す。"""
    return build_dump(work_dir).fixtures


def build_dump(work_dir: Path) -> Dump:
    """build_fixtures と同じ台本を流し、印刷の経路の検査の要約も返す。"""
    work_dir = Path(work_dir)
    with _fixed_world():
        home = _copy_skills_home(work_dir)
        settings = make_settings(
            work_dir,
            skills_dir=home / ".claude" / "skills",
            public_base_url=PUBLIC_BASE_URL,
        )
        app = make_app(
            work_dir, runner=_demo_runner(), editor=ScriptedEditor(), settings=settings
        )
        return _run(app, home)


# ---------------------------------------------------------------------------
# 書き出し
# ---------------------------------------------------------------------------


def render(data: Any) -> str:
    """fixture 1件のファイルの中身（2字下げ・日本語はそのまま・末尾に改行）。"""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_fixtures(fixtures: dict[str, Any], out_dir: Path) -> list[Path]:
    """`<名前>.json` を書き、out_dir の他の *.json（消えた経路の古い fixture）を消す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = {f"{name}.json" for name in fixtures}
    for old in out_dir.glob("*.json"):
        if old.name not in wanted:
            old.unlink()
    written = []
    for name, data in sorted(fixtures.items()):
        path = out_dir / f"{name}.json"
        path.write_text(render(data), encoding="utf-8")
        written.append(path)
    return written


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="書き出す先")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    with tempfile.TemporaryDirectory(prefix="tsutae-fixtures-") as tmp:
        fixtures = build_fixtures(Path(tmp))
    written = write_fixtures(fixtures, args.out)
    print(f"{len(written)} 件を {args.out} に書いた")
    return 0


if __name__ == "__main__":
    sys.exit(main())

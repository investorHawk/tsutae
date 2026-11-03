"""API テストの共通の作り方（患者側・医師側の両方が使う。API は呼ばない）。

使い方::

    from api_helpers import api_client, add_patient, register

    def test_x(tmp_path):
        with api_client(tmp_path) as client:          # 起動処理（init_db 等）が走る
            pid = add_patient(client.app, courses=[(1, date(2026, 10, 27))])
            register(client, pid)                      # Cookie tsutae_pid が付く
            ...

- **TestClient は必ず `with` で開く**（`api_client` がそうする）。素の `TestClient(app)` は
  lifespan を走らせず、表が無いまま（no such table）になる
- DB は tmp_path の下。runner は `pipeline_fakes.FakeRunner`（既定は台本なし）、
  editor は `FakeEditor`（既定は何もしない）
- 患者の Cookie は `set_patient_cookie(client, pid)`（`register` を使わず、deps の署名で
  直接作る）
- 医師の Cookie は `login_doctor(client)`（`POST /api/doctor/login` を使わず、deps の
  署名で直接作る。医師 API が無くても使える）
"""

from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner

from tsutae import db
from tsutae.api.app import create_app
from tsutae.api.deps import (
    DOCTOR_COOKIE,
    PATIENT_COOKIE,
    is_patient_id,
    make_doctor_token,
    make_patient_token,
)
from tsutae.config import REPO_ROOT, SKILLS_DIR, Settings, get_settings, now
from tsutae.schemas import Course, EntryCreate, RunStats
from tsutae.skillchange.workcopy import work_copy_path

TEST_PASSWORD = "test-doctor-password"
TEST_SECRET = "test-secret-key"
SEED_SCRIPT = REPO_ROOT / "scripts" / "seed_demo.py"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """tmp_path の DB と同梱の Skill を使う設定（環境変数の値に左右されない）。"""
    base = replace(
        get_settings(),
        db_path=tmp_path / "api.db",
        skills_dir=SKILLS_DIR,
        doctor_password=TEST_PASSWORD,
        secret_key=TEST_SECRET,
        report_ttl_hours=24,
        public_base_url="http://testserver",
    )
    return replace(base, **overrides)


@dataclass
class RunnerFactory:
    """`app.state.runner_factory` の偽物。毎回同じ runner を返し、呼ばれた回数を数える。"""

    runner: Any = field(default_factory=FakeRunner)
    calls: int = 0

    def __call__(self) -> Any:
        self.calls += 1
        return self.runner


@dataclass
class FakeEditor:
    """SkillEditor の偽物。transform があれば作業コピーの SKILL.md に掛ける。"""

    transform: Callable[[str], str] | None = None
    stats: RunStats = field(default_factory=RunStats)
    calls: list[tuple[Path, str, str]] = field(default_factory=list)

    async def edit(
        self, work_root: Path, skill_name: str, request_text: str
    ) -> RunStats:
        self.calls.append((Path(work_root), skill_name, request_text))
        if self.transform is not None:
            path = work_copy_path(Path(work_root), skill_name)
            path.write_text(self.transform(path.read_text(encoding="utf-8")), "utf-8")
        return self.stats


def make_app(
    tmp_path: Path,
    *,
    runner: Any = None,
    editor: Any = None,
    settings: Settings | None = None,
    **overrides: Any,
) -> FastAPI:
    resolved = settings or make_settings(tmp_path, **overrides)
    return create_app(
        resolved,
        runner_factory=RunnerFactory(runner if runner is not None else FakeRunner()),
        skill_editor=editor if editor is not None else FakeEditor(),
    )


@contextmanager
def api_client(
    tmp_path: Path,
    *,
    runner: Any = None,
    editor: Any = None,
    settings: Settings | None = None,
    **overrides: Any,
) -> Iterator[TestClient]:
    """起動処理（init_db・ensure_skill_versions・purge_expired）を済ませた TestClient。"""
    app = make_app(
        tmp_path, runner=runner, editor=editor, settings=settings, **overrides
    )
    with TestClient(app) as client:
        yield client


@contextmanager
def db_conn(app: FastAPI) -> Iterator[sqlite3.Connection]:
    """アプリと同じ DB への別の接続（テストの準備・確認用）。"""
    conn = db.connect(app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def add_patient(
    app: FastAPI,
    regimen: str = "FOLFOX",
    *,
    courses: Sequence[tuple[int, date]] = (),
    patient_id: str | None = None,
) -> str:
    """患者とコース（(course_no, 実投与日)）を入れて仮名IDを返す。"""
    with db_conn(app) as conn:
        pid = db.create_patient(conn, regimen, patient_id=patient_id)
        for course_no, infusion in courses:
            db.upsert_course(
                conn,
                Course(patient_id=pid, course_no=course_no, infusion_date=infusion),
            )
    return pid


def add_entry(
    app: FastAPI,
    pid: str,
    entry: EntryCreate,
    *,
    skill_version: str = "regimen-folfox@1",
) -> int:
    with db_conn(app) as conn:
        return db.add_entry(conn, pid, entry, now(), skill_version).id


def register(client: TestClient, pid: str) -> Any:
    """患者の登録（Cookie tsutae_pid が client に付く）。"""
    return client.post("/api/patient/register", json={"pid": pid})


def set_patient_cookie(client: TestClient, pid: str) -> None:
    """患者の Cookie を deps の署名で直接付ける（仮名IDの形でなければ値をそのまま）。"""
    if is_patient_id(pid):
        value = make_patient_token(client.app.state.settings.secret_key, pid)
    else:
        value = pid
    client.cookies.set(PATIENT_COOKIE, value)


def login_doctor(client: TestClient) -> None:
    """医師の Cookie を deps の署名で直接付ける。"""
    token = make_doctor_token(client.app.state.settings.secret_key, now())
    client.cookies.set(DOCTOR_COOKIE, token)


def load_seed_module() -> ModuleType:
    """scripts/seed_demo.py をモジュールとして読む（scripts は import 経路に無い）。"""
    spec = importlib.util.spec_from_file_location("seed_demo", SEED_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SEED_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_synthetic(app: FastAPI) -> list[str]:
    """合成3人（デモ・評価2人）を入れる（seed_demo.seed と同じ）。追加した仮名ID。"""
    seed = load_seed_module()
    with db_conn(app) as conn:
        return seed.seed(conn, skills_dir=app.state.settings.skills_dir)

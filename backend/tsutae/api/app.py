"""FastAPI アプリ（docs/architecture.md §8b）。`uvicorn tsutae.api.app:app` で起動する。

- `create_app(settings=None, *, runner_factory=None, skill_editor=None)`。`app.state` に
  settings・runner_factory（既定 `SdkRunner`）・skill_editor（既定 `SdkSkillEditor`。
  `tsutae.skillchange` が無ければ None）・skills_home を置く
- create_app は設定を検査する（`settings_check`。公開の構成で既定の鍵・パスワードなら
  `InsecureSettingsError` で起動しない。手元では警告だけ）
- 起動時（lifespan）に `init_db`・`ensure_skill_versions`・`purge_expired`。起動中は
  `PURGE_INTERVAL_S` ごとに `purge_once` を回す周期タスク（`app.state.purge_task`）を
  置き、終了時に止める（医師 API が呼ばれなくても期限切れの中身を消す）
- 最も外側に `SuppressServerErrors` を置く（想定外の例外を uvicorn へ投げ直さない）
- 医師 API（`tsutae.api.doctor`・`tsutae.api.doctor_skills`）は、モジュールがあれば
  `router` を載せる（無ければ飛ばす。中の import の失敗は隠さない）
- モジュールの `app` は初めて参照されたときに作る（`.env` もそのとき読む）
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp

from tsutae import db
from tsutae.api import patient, visit
from tsutae.api.deps import install_error_handlers
from tsutae.api.error_guard import SuppressServerErrors
from tsutae.api.settings_check import check_settings
from tsutae.config import Settings, get_settings, load_env_file, now
from tsutae.pipeline.runner import SdkRunner
from tsutae.pipeline.service import ensure_skill_versions

__all__ = [
    "OPTIONAL_ROUTERS",
    "PURGE_INTERVAL_S",
    "create_app",
    "purge_once",
    "startup",
]

OPTIONAL_ROUTERS = ("tsutae.api.doctor", "tsutae.api.doctor_skills")
SKILLCHANGE_MODULE = "tsutae.skillchange"
PURGE_INTERVAL_S = 600.0
_log = logging.getLogger(__name__)
_app: FastAPI | None = None


def startup(settings: Settings) -> int:
    """表を作り、今の Skill の版を登録し、期限切れの受診を消す。消した件数を返す。"""
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        ensure_skill_versions(conn, settings.skills_dir)
        return db.purge_expired(conn, now())
    finally:
        conn.close()


def purge_once(settings: Settings) -> int:
    """自分の接続で期限切れの受診を1回消し、件数を返す。"""
    conn = db.connect(settings.db_path)
    try:
        return db.purge_expired(conn, now())
    finally:
        conn.close()


async def _purge_loop(settings: Settings, interval_s: float) -> None:
    """interval_s ごとに purge_once を回す。失敗は型名だけ残して次の周期へ。"""
    while True:
        await asyncio.sleep(interval_s)
        try:
            purged = await asyncio.to_thread(purge_once, settings)
        except Exception as exc:  # noqa: BLE001 — 掃除の失敗でサーバを止めない
            _log.warning("api.purge_failed error_type=%s", type(exc).__name__)
            continue
        if purged:
            _log.info("期限切れの受診 %d 件を消した", purged)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    purged = startup(app.state.settings)
    if purged:
        _log.info("期限切れの受診 %d 件を消した", purged)
    task = asyncio.create_task(_purge_loop(app.state.settings, PURGE_INTERVAL_S))
    app.state.purge_task = task
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class _TsutaeApp(FastAPI):
    """ミドルウェアの積み上げの最も外側（ServerErrorMiddleware の外）にガードを置く。"""

    def build_middleware_stack(self) -> ASGIApp:
        return SuppressServerErrors(super().build_middleware_stack())


def _is_missing(exc: ImportError, module_name: str) -> bool:
    """module_name（かその親）そのものが無い ImportError か。"""
    name = getattr(exc, "name", None) or ""
    if not isinstance(exc, ModuleNotFoundError) or not name:
        return False
    return module_name == name or module_name.startswith(name + ".")


def _include_optional(app: FastAPI, module_name: str) -> bool:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if _is_missing(exc, module_name):
            _log.info("%s が無いので載せない", module_name)
            return False
        raise
    app.include_router(module.router)
    return True


def _default_skill_editor(settings: Settings) -> Any:
    """`tsutae.skillchange.SdkSkillEditor`。モジュールが無ければ None。"""
    try:
        module = importlib.import_module(SKILLCHANGE_MODULE)
    except ModuleNotFoundError as exc:
        if _is_missing(exc, SKILLCHANGE_MODULE):
            return None
        raise
    editor_cls = getattr(module, "SdkSkillEditor", None)
    if editor_cls is None:
        return None
    params = inspect.signature(editor_cls).parameters
    return editor_cls(settings=settings) if "settings" in params else editor_cls()


def skills_home_of(settings: Settings) -> Path:
    """skills_dir（`<skills_home>/.claude/skills`）から skills_home を求める。"""
    return Path(settings.skills_dir).parent.parent


def create_app(
    settings: Settings | None = None,
    *,
    runner_factory: Callable[[], Any] | None = None,
    skill_editor: Any = None,
) -> FastAPI:
    resolved = settings if settings is not None else get_settings()
    check_settings(resolved)
    app = _TsutaeApp(
        title="tsutae",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = resolved
    app.state.runner_factory = runner_factory or SdkRunner
    app.state.skill_editor = (
        skill_editor if skill_editor is not None else _default_skill_editor(resolved)
    )
    app.state.skills_home = skills_home_of(resolved)
    install_error_handlers(app)
    app.include_router(patient.router)
    app.include_router(visit.router)
    app.state.optional_routers = tuple(
        name for name in OPTIONAL_ROUTERS if _include_optional(app, name)
    )
    return app


def __getattr__(name: str) -> Any:
    """`tsutae.api.app:app` を初めて参照したときに作る（import だけでは作らない）。"""
    global _app
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _app is None:
        load_env_file()
        _app = create_app()
    return _app

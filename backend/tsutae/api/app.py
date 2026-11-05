"""FastAPI アプリ（docs/architecture.md §8b）。`uvicorn tsutae.api.app:app` で起動する。

- `create_app(settings=None, *, runner_factory=None, skill_editor=None,
  regimen_chat=None, push_sender=None)`。`app.state` に settings・runner_factory（既定
  `SdkRunner`）・skill_editor（既定 `SdkSkillEditor`。`tsutae.skillchange` が無ければ None）・
  regimen_chat（D4 レジメンの1往復。既定 `SdkRegimenChat`）・skills_home・push_sender（既定は
  VAPID の鍵があれば `WebPushSender`、無ければ None で通知を使えない）を置く
- create_app は設定を検査する（`settings_check`。公開の構成で既定の鍵・パスワードなら
  `InsecureSettingsError` で起動しない。手元では警告だけ）
- 起動時（lifespan）に `init_db`・`ensure_skill_versions`・`seed_question_library`
  （質問の部品集の初期6問）・`recover_abandoned_turns`（working の取り残しを open に）・
  `recover_interrupted_adoptions`（採用の途中の回復）・`purge_expired`。起動中は
  `PURGE_INTERVAL_S` ごとに `purge_once` を回す周期タスク（`app.state.purge_task`）を
  置き、終了時に止める（医師 API が呼ばれなくても期限切れの中身を消す）
- 起動時（purge の後・リクエストを受ける前）に1回だけ `orphans.recover_orphans`:
  生成中のまま残った受診（前のプロセスが変換中に止まった）を Claude を呼ばずに
  AI 変換なしのレポートにする
- 周期タスクでは purge の後に `orphans.recover_stale`: 動きの無い generating
  （最後のログから pipeline_timeout_s + 120 秒以上）だけを同じやり方で救う
  （稼働中に生成が DB を開けずに抜けた受診を、再起動を待たずに回収する）
- 起動中は `PUSH_INTERVAL_S` ごとに毎日の通知の対象を探して送る周期タスク
  （`app.state.push_task`）も置く。`_purge_loop` と同じ形で、例外で止めない。sender は毎回
  `app.state.push_sender` から読む。`--workers 1` が前提（plan-device-records §4.3）
- 最も外側に `SuppressServerErrors` を置く（想定外の例外を uvicorn へ投げ直さない）
- 医師 API（`tsutae.api.doctor`・`tsutae.api.doctor_skills`・
  `tsutae.api.doctor_question_library`・`tsutae.api.doctor_regimen_drafts`）は、モジュールがあれば
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
from tsutae.api import orphans, patient, patient_push, visit
from tsutae.api.deps import install_error_handlers
from tsutae.api.error_guard import SuppressServerErrors
from tsutae.api.settings_check import check_settings
from tsutae.config import Settings, get_settings, load_env_file, now
from tsutae.pipeline.runner import SdkRunner
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.push.dispatch import send_due_once
from tsutae.push.sender import WebPushSender, load_vapid
from tsutae.regimen.chat_sdk import SdkRegimenChat
from tsutae.regimen.recover import (
    recover_abandoned_turns,
    recover_interrupted_adoptions,
)

__all__ = [
    "OPTIONAL_ROUTERS",
    "PURGE_INTERVAL_S",
    "PUSH_INTERVAL_S",
    "create_app",
    "purge_once",
    "startup",
]

OPTIONAL_ROUTERS = (
    "tsutae.api.doctor",
    "tsutae.api.doctor_skills",
    "tsutae.api.doctor_question_library",
    "tsutae.api.doctor_regimen_drafts",
)
SKILLCHANGE_MODULE = "tsutae.skillchange"
PURGE_INTERVAL_S = 600.0
PUSH_INTERVAL_S = 60.0
_log = logging.getLogger(__name__)
_app: FastAPI | None = None


def startup(settings: Settings) -> int:
    """表を作り、今の Skill の版を登録し、期限切れの受診を消す。消した件数を返す。"""
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        ensure_skill_versions(conn, settings.skills_dir)
        db.seed_question_library(conn)
        # working の取り残し（前のプロセスの往復）を先に open に戻す（回復は open だけを見る）
        abandoned = recover_abandoned_turns(conn)
        if abandoned:
            _log.info("往復の途中で止まった下書き %d 件を open に戻した", abandoned)
        recovered = recover_interrupted_adoptions(conn, settings.skills_dir)
        if recovered:
            _log.info("採用の途中で止まった下書き %d 件を補った", recovered)
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


async def _recover_stale_once(settings: Settings) -> None:
    """動きの無い generating を救う。失敗は型名だけ残す（周期を止めない）。"""
    try:
        recovered = await orphans.recover_stale(settings, now=now())
    except Exception as exc:  # noqa: BLE001 — 回収の失敗でサーバを止めない
        _log.warning("api.stale_recover_failed error_type=%s", type(exc).__name__)
        return
    if recovered:
        _log.info("動きの無い生成中の受診 %d 件を AI 変換なしにした", recovered)


async def _purge_loop(settings: Settings, interval_s: float) -> None:
    """interval_s ごとに purge_once と recover_stale を回す。失敗は型名だけ残す。"""
    while True:
        await asyncio.sleep(interval_s)
        try:
            purged = await asyncio.to_thread(purge_once, settings)
        except Exception as exc:  # noqa: BLE001 — 掃除の失敗でサーバを止めない
            _log.warning("api.purge_failed error_type=%s", type(exc).__name__)
            purged = 0
        if purged:
            _log.info("期限切れの受診 %d 件を消した", purged)
        await _recover_stale_once(settings)


async def _push_loop(app: FastAPI, interval_s: float) -> None:
    """interval_s ごとに毎日の通知を送る。失敗は型名だけ残す。"""
    while True:
        await asyncio.sleep(interval_s)
        sender = app.state.push_sender
        if sender is None:
            continue
        try:
            await asyncio.to_thread(send_due_once, app.state.settings, sender)
        except Exception as exc:  # noqa: BLE001 — 通知の失敗でサーバを止めない
            _log.warning("api.push_failed error_type=%s", type(exc).__name__)


async def _stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    purged = startup(app.state.settings)
    if purged:
        _log.info("期限切れの受診 %d 件を消した", purged)
    recovered = await orphans.recover_orphans(app.state.settings)
    if recovered:
        _log.info("生成中のまま残った受診 %d 件を AI 変換なしにした", recovered)
    task = asyncio.create_task(_purge_loop(app.state.settings, PURGE_INTERVAL_S))
    app.state.purge_task = task
    push_task = asyncio.create_task(_push_loop(app, PUSH_INTERVAL_S))
    app.state.push_task = push_task
    try:
        yield
    finally:
        await _stop(push_task)
        await _stop(task)


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


def _install_push(app: FastAPI, settings: Settings, push_sender: Any) -> None:
    """通知の状態を app.state に置く。鍵が無くても起動を止めない。"""
    vapid = load_vapid(settings)
    app.state.push_public_key = vapid.public_key if vapid is not None else None
    if push_sender is not None:
        app.state.push_sender = push_sender
    else:
        app.state.push_sender = WebPushSender(vapid) if vapid is not None else None
    app.state.push_test_limiter = patient_push.PushTestLimiter()
    app.state.push_test_delay_s = patient_push.PUSH_TEST_DELAY_S


def create_app(
    settings: Settings | None = None,
    *,
    runner_factory: Callable[[], Any] | None = None,
    skill_editor: Any = None,
    regimen_chat: Any = None,
    push_sender: Any = None,
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
    app.state.regimen_chat = (
        regimen_chat if regimen_chat is not None else SdkRegimenChat(resolved)
    )
    app.state.skills_home = skills_home_of(resolved)
    _install_push(app, resolved, push_sender)
    install_error_handlers(app)
    app.include_router(patient.router)
    app.include_router(patient_push.router)
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

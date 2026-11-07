"""起動時に、生成中のまま残った受診を AI 変換なしで救う（spec 6 のフォールバック）。

変換は同じプロセスの BackgroundTasks で動く（`tsutae.api.visit`）。変換中にサーバーが
止まる・再起動する（`--reload` を含む）と、その受診は status=generating のまま残る。

- `recover_orphans(settings)` は lifespan が purge の後・リクエストを受ける前に1回だけ
  呼ぶ（全ての generating を取るので周期タスクには入れない。周期タスクは
  下の `recover_stale` で、動きの無いものだけを取る）
- 対象は受付番号が残っていて期限（expires_at）前の generating だけ。印刷済み・
  期限切れ・ready・failed には触れない
- 生成は `visit.run_generation` に必ず失敗する `OrphanRunner` を渡して回す（Claude を
  呼ばない）。convert が `internal_error`（error_type `OrphanedVisitError`）の
  フォールバックにし、service が AI 変換なしのレポートで ready（fallback=True）にする。
  入力が作れなければ service が failed にする。自由記載が無ければ AI は要らないので、
  通常と同じく fallback=False で ready になる
- 回収は費用がかからず全ての記録を読むので、自動の変換し直しの回数（plan-device-records §6）を
  使わない。それまでに届いた分の印（regen_pending）は先に下ろし、回収の最中に届いた分は
  数えずにもう1回読む（`recover_stale` はリクエストを受けながら動く）
- `recover_stale(settings, *, now, stale_after)` は purge の周期タスクから呼ぶ。稼働中に
  バックグラウンドの生成が DB を開けずに抜ける等で generating のまま残った受診を、
  次の再起動を待たずに同じやり方で救う。対象は「動きの無い」generating だけ
  （その受診の pipeline_logs（run_kind=visit）の最後の ts、無ければ visits.created_at
  から stale_after 以上たったもの）。stale_after の既定は pipeline_timeout_s + 120 秒
  なので、今まさに動いている生成（最後のログが新しい）は奪わない
- 1件ごとに pipeline_logs へ `orphan_recovered`（decision `status:<結果の状態>`）を残し、
  アプリのログにも id と状態だけを書く（文面なし）。1件の失敗で他を止めない
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from tsutae import db
from tsutae.api import visit
from tsutae.config import Settings
from tsutae.config import now as clock_now
from tsutae.pipeline.logs import PipelineLogger, reason_code
from tsutae.schemas import RunStats

__all__ = [
    "ORPHAN_EVENT",
    "OrphanRunner",
    "OrphanedVisitError",
    "find_orphans",
    "find_stale",
    "recover_orphans",
    "recover_stale",
    "stale_after_for",
]

ORPHAN_EVENT = "orphan_recovered"
RUN_KIND = "visit"
STALE_MARGIN_S = 120.0
_log = logging.getLogger(__name__)


class OrphanedVisitError(RuntimeError):
    """起動時に救う受診の変換で投げる（Claude を呼ばずにフォールバックへ回す印）。"""


class OrphanRunner:
    """AgentRunner の代わり。呼ばれたら必ず失敗する（Claude を呼ばない）。"""

    async def run(self, prompt: str, options: Any, collector: Any) -> RunStats:
        raise OrphanedVisitError("orphaned visit: Claude を呼ばない")


def _active_generating(
    conn: sqlite3.Connection, current: datetime
) -> list[dict[str, Any]]:
    visits = db.list_visits(conn, ("generating",), active_only=True)
    return [
        v for v in visits if v["expires_at"] is not None and v["expires_at"] > current
    ]


def find_orphans(conn: sqlite3.Connection) -> list[int]:
    """受付番号が残っていて期限前の generating の受診の id（受付順）。"""
    return [int(v["id"]) for v in _active_generating(conn, clock_now())]


def stale_after_for(settings: Settings) -> timedelta:
    """動きが無いとみなすまでの時間（生成のタイムアウト + 余裕）。"""
    return timedelta(seconds=settings.pipeline_timeout_s + STALE_MARGIN_S)


def _last_activity(conn: sqlite3.Connection, visit: dict[str, Any]) -> datetime:
    logs = db.list_pipeline_logs(conn, RUN_KIND, int(visit["id"]))
    times = [log["ts"] for log in logs if log["ts"] is not None]
    return max(times) if times else visit["created_at"]


def find_stale(
    conn: sqlite3.Connection, current: datetime, stale_after: timedelta
) -> list[int]:
    """find_orphans のうち、最後の動きから stale_after 以上たった受診の id。"""
    return [
        int(v["id"])
        for v in _active_generating(conn, current)
        if current - _last_activity(conn, v) >= stale_after
    ]


def _list_orphans(settings: Settings) -> list[int]:
    conn = db.connect(settings.db_path)
    try:
        return find_orphans(conn)
    finally:
        conn.close()


def _list_stale(
    settings: Settings, current: datetime, stale_after: timedelta
) -> list[int]:
    conn = db.connect(settings.db_path)
    try:
        return find_stale(conn, current, stale_after)
    finally:
        conn.close()


def _clear_pending(settings: Settings, visit_id: int) -> None:
    conn = db.connect(settings.db_path)
    try:
        db.clear_regen_pending(conn, visit_id)
    finally:
        conn.close()


def _record(settings: Settings, visit_id: int) -> str:
    """結果の状態を読み直し、`orphan_recovered` を残す。状態を返す。"""
    conn = db.connect(settings.db_path)
    try:
        row = db.get_visit(conn, visit_id)
        status = "missing" if row is None else str(row["status"])
        PipelineLogger(conn, RUN_KIND, visit_id).event(
            ORPHAN_EVENT, decision=reason_code("status", status)
        )
    finally:
        conn.close()
    _log.info("api.%s visit_id=%s status=%s", ORPHAN_EVENT, visit_id, status)
    return status


async def _recover_one(settings: Settings, visit_id: int) -> bool:
    """1件を救う。ready になれば True。例外は外へ出さない（型名だけ残す）。"""
    try:
        _clear_pending(settings, visit_id)
        await visit.run_generation(settings, OrphanRunner, visit_id, counted=False)
        return _record(settings, visit_id) == "ready"
    except Exception as exc:  # noqa: BLE001 — 1件の失敗で他を止めない
        _log.warning(
            "api.orphan_failed visit_id=%s error_type=%s",
            visit_id,
            type(exc).__name__,
        )
        return False


async def _recover_all(ids: list[int], settings: Settings) -> int:
    recovered = 0
    for visit_id in ids:
        if await _recover_one(settings, visit_id):
            recovered += 1
    return recovered


async def recover_orphans(settings: Settings) -> int:
    """生成中のまま残った受診を全て AI 変換なしで救い、ready にできた件数を返す。"""
    try:
        ids = _list_orphans(settings)
    except Exception as exc:  # noqa: BLE001 — 回収の失敗で起動を止めない
        _log.warning("api.orphan_scan_failed error_type=%s", type(exc).__name__)
        return 0
    return await _recover_all(ids, settings)


async def recover_stale(
    settings: Settings,
    *,
    now: datetime | None = None,
    stale_after: timedelta | None = None,
) -> int:
    """動きの無い generating だけを AI 変換なしで救い、ready にできた件数を返す。

    now の既定は今の時刻、stale_after の既定は `stale_after_for(settings)`。
    """
    current = clock_now() if now is None else now
    limit = stale_after_for(settings) if stale_after is None else stale_after
    try:
        ids = _list_stale(settings, current, limit)
    except Exception as exc:  # noqa: BLE001 — 回収の失敗で掃除の周期を止めない
        _log.warning("api.orphan_scan_failed error_type=%s", type(exc).__name__)
        return 0
    return await _recover_all(ids, settings)

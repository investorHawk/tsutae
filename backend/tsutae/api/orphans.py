"""起動時に、生成中のまま残った受診を AI 変換なしで救う（spec 6 のフォールバック）。

変換は同じプロセスの BackgroundTasks で動く（`tsutae.api.visit`）。変換中にサーバーが
止まる・再起動する（`--reload` を含む）と、その受診は status=generating のまま残る。

- `recover_orphans(settings)` は lifespan が purge の後・リクエストを受ける前に1回だけ
  呼ぶ（周期タスクには入れない。同じプロセスで今まさに生成中の受診を奪わない）
- 対象は受付番号が残っていて期限（expires_at）前の generating だけ。印刷済み・
  期限切れ・ready・failed には触れない
- 生成は `visit.run_generation` に必ず失敗する `OrphanRunner` を渡して回す（Claude を
  呼ばない）。convert が `internal_error`（error_type `OrphanedVisitError`）の
  フォールバックにし、service が AI 変換なしのレポートで ready（fallback=True）にする。
  入力が作れなければ service が failed にする。自由記載が無ければ AI は要らないので、
  通常と同じく fallback=False で ready になる
- 1件ごとに pipeline_logs へ `orphan_recovered`（decision `status:<結果の状態>`）を残し、
  アプリのログにも id と状態だけを書く（文面なし）。1件の失敗で他を止めない
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from tsutae import db
from tsutae.api import visit
from tsutae.config import Settings, now
from tsutae.pipeline.logs import PipelineLogger, reason_code
from tsutae.schemas import RunStats

__all__ = [
    "ORPHAN_EVENT",
    "OrphanRunner",
    "OrphanedVisitError",
    "find_orphans",
    "recover_orphans",
]

ORPHAN_EVENT = "orphan_recovered"
RUN_KIND = "visit"
_log = logging.getLogger(__name__)


class OrphanedVisitError(RuntimeError):
    """起動時に救う受診の変換で投げる（Claude を呼ばずにフォールバックへ回す印）。"""


class OrphanRunner:
    """AgentRunner の代わり。呼ばれたら必ず失敗する（Claude を呼ばない）。"""

    async def run(self, prompt: str, options: Any, collector: Any) -> RunStats:
        raise OrphanedVisitError("orphaned visit: Claude を呼ばない")


def find_orphans(conn: sqlite3.Connection) -> list[int]:
    """受付番号が残っていて期限前の generating の受診の id（受付順）。"""
    current = now()
    visits = db.list_visits(conn, ("generating",), active_only=True)
    return [
        int(v["id"])
        for v in visits
        if v["expires_at"] is not None and v["expires_at"] > current
    ]


def _list_orphans(settings: Settings) -> list[int]:
    conn = db.connect(settings.db_path)
    try:
        return find_orphans(conn)
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
        await visit.run_generation(settings, OrphanRunner, visit_id)
        return _record(settings, visit_id) == "ready"
    except Exception as exc:  # noqa: BLE001 — 1件の失敗で他を止めない
        _log.warning(
            "api.orphan_failed visit_id=%s error_type=%s",
            visit_id,
            type(exc).__name__,
        )
        return False


async def recover_orphans(settings: Settings) -> int:
    """生成中のまま残った受診を全て AI 変換なしで救い、ready にできた件数を返す。"""
    try:
        ids = _list_orphans(settings)
    except Exception as exc:  # noqa: BLE001 — 回収の失敗で起動を止めない
        _log.warning("api.orphan_scan_failed error_type=%s", type(exc).__name__)
        return 0
    recovered = 0
    for visit_id in ids:
        if await _recover_one(settings, visit_id):
            recovered += 1
    return recovered

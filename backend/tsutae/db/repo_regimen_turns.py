"""D4 レジメンの1往復の終わりの書き込み（regimen_drafts。T94、architecture 9c）。

どちらも「working かつ同じ generation」の行だけを open に戻す（条件付きの UPDATE）。
往復の間に回復（`recover_stale_working`）が open に戻した・次の往復が始まった下書きには
書かない（False。遅れた結果・失敗の行を捨てる）。

- `finish_turn`: フォーム・出どころ・識別名・会話を書いて open に戻す。識別名が別の
  開いた下書きとぶつかれば `DraftConflictError("code_taken")`
- `fail_turn`: 会話（先生の文と失敗の行を足したもの）だけを書いて open に戻す
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from tsutae.config import now as clock_now
from tsutae.db.connection import dt_to_db, write_transaction
from tsutae.db.repo_regimen_drafts import DraftConflictError

__all__ = ["fail_turn", "finish_turn"]

_WHERE = " WHERE id = ? AND status = 'working' AND generation = ?"


def _chat_json(chat: Sequence[dict[str, Any]]) -> str:
    return json.dumps(list(chat), ensure_ascii=False)


def finish_turn(
    conn: sqlite3.Connection,
    draft_id: int,
    generation: int,
    *,
    form_json: str,
    sources_json: str,
    regimen: str | None,
    chat: Sequence[dict[str, Any]],
) -> bool:
    """往復の結果を書いて open に戻す。working・同じ generation でなければ False。"""
    stamp = dt_to_db(clock_now())
    try:
        with write_transaction(conn):
            cur = conn.execute(
                "UPDATE regimen_drafts SET status = 'open', working_since = NULL,"
                " form_json = ?, sources_json = ?, regimen = ?, chat_json = ?,"
                " updated_at = ?" + _WHERE,
                (
                    form_json,
                    sources_json,
                    regimen,
                    _chat_json(chat),
                    stamp,
                    draft_id,
                    generation,
                ),
            )
    except sqlite3.IntegrityError as exc:
        text = str(exc)
        if "UNIQUE" in text and "regimen_drafts.regimen" in text:
            raise DraftConflictError("code_taken") from None
        raise
    return cur.rowcount > 0


def fail_turn(
    conn: sqlite3.Connection,
    draft_id: int,
    generation: int,
    *,
    chat: Sequence[dict[str, Any]],
) -> bool:
    """会話だけを書いて open に戻す（フォームは変えない）。条件は finish_turn と同じ。"""
    stamp = dt_to_db(clock_now())
    with write_transaction(conn):
        cur = conn.execute(
            "UPDATE regimen_drafts SET status = 'open', working_since = NULL,"
            " chat_json = ?, updated_at = ?" + _WHERE,
            (_chat_json(chat), stamp, draft_id, generation),
        )
    return cur.rowcount > 0

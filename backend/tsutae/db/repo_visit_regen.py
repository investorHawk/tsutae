"""受付の後に記録が増えた受診の変換し直し（plan-device-records §6。2台目のスマホ）。

変換は患者の全ての記録を読むので、新しい記録はその患者のその日の開いた受診の全てに足りない
（番号を間違えて別の受診ができたときも、どちらも全ての記録で変換する）。だから新しい記録が
入るたびに、番号を問わずそれらの受診を動かす（`begin_added_records_on_open_visits`）。

visits の2列で表す:

- regen_pending: この受診の変換に入っていない記録がある。生成中に届いたか、自動の回数を
  使い切った後に届いたときに立つ。自動の回数が残っていれば生成の終わりに下ろして変換し直す。
  使い切っていれば立ったまま残り、D3 の「追加の記録あり」になる（医師が押すと下りる）
- regen_count: 記録が増えて自動で変換し直した回数。`REGEN_AUTO_MAX` まで（費用の歯止め）。
  医師の「AI でもう一度変換」と、Claude を呼ばない回収（`api.orphans`）は数えない

印刷が前のレポートで割り込まないように、状態の変更は記録の保存・結果の保存と同じ
トランザクションで行う（呼び出し側で write_transaction を開く関数は、その旨を書いた）。
だから ready のまま regen_pending が立っているのは、回数を使い切ったときだけ。
"""

from __future__ import annotations

import sqlite3

from tsutae.config import now as clock_now
from tsutae.db.connection import dt_to_db, write_transaction

__all__ = [
    "REGEN_AUTO_MAX",
    "STATUS_GUARD",
    "begin_added_records",
    "begin_added_records_on_open_visits",
    "clear_regen_pending",
    "hold_for_regeneration",
    "take_regen_pending",
]

REGEN_AUTO_MAX = 3

# 閉じた受診（印刷済み・受付番号を消した・期限を過ぎた）は条件付き UPDATE で触らない。
# 別の接続の mark_printed と競合しても printed を ready に戻さない。期限の比較は
# purge_expired（expires_at <= now で消す）と同じ境界: expires_at > now の間だけ開いている。
# 日時は固定幅の JST 文字列なので、文字列の比較が時刻の順と一致する（connection.py）
STATUS_GUARD = (
    " AND reception_no IS NOT NULL AND status != 'printed' AND expires_at > ?"
)

# 自動で変換し直す（回数が残っている開いた受診を generating に戻す）。結果は次の保存が決めるので
# fallback は下ろす。レポートと変換結果は残す（新しい生成が上書きする）
_BACK_TO_GENERATING = (
    "UPDATE visits SET status = 'generating', fallback = 0, regen_pending = 0"
)
_OPEN_WITH_RUNS_LEFT = " WHERE id = ?" + STATUS_GUARD + " AND regen_count < ?"
_START_AUTO = (
    _BACK_TO_GENERATING + ", regen_count = regen_count + 1" + _OPEN_WITH_RUNS_LEFT
)
# Claude を呼ばない回収の周回。費用がかからないので回数に数えない
_START_UNCOUNTED = _BACK_TO_GENERATING + _OPEN_WITH_RUNS_LEFT


def begin_added_records(conn: sqlite3.Connection, vid: int, now_db: str) -> bool:
    """新しい記録が届いた受診の、begin_regeneration の入口。始めたら True。

    ready（AI の結果でも）・failed で回数が残っていれば generating に戻す。生成中や回数を
    使い切った後は regen_pending だけを立てて False。write_transaction の内側で、記録の
    保存と一緒に呼ぶ。
    """
    cur = conn.execute(
        _START_AUTO + " AND status IN ('ready', 'failed')",
        (vid, now_db, REGEN_AUTO_MAX),
    )
    if cur.rowcount > 0:
        return True
    conn.execute(
        "UPDATE visits SET regen_pending = 1 WHERE id = ?" + STATUS_GUARD,
        (vid, now_db),
    )
    return False


def begin_added_records_on_open_visits(
    conn: sqlite3.Connection, pid: str, day: str | None, now_db: str
) -> tuple[int, ...]:
    """その患者のその日の開いた受診を全て `begin_added_records` に通す。

    始めた（generating に戻した）受診の id を受付順で返す。write_transaction の内側で、
    記録の保存と一緒に呼ぶ。別の日の受診は読む範囲も受付も別なので動かさない。
    """
    rows = conn.execute(
        "SELECT id FROM visits WHERE patient_id = ? AND visit_date = ?"
        + STATUS_GUARD
        + " ORDER BY id",
        (pid, day, now_db),
    ).fetchall()
    return tuple(
        int(r["id"]) for r in rows if begin_added_records(conn, int(r["id"]), now_db)
    )


def hold_for_regeneration(conn: sqlite3.Connection, vid: int) -> None:
    """結果を保存した受診に待っている分があれば、ready を見せずに generating のままにする。

    回数を使い切っていれば ready のまま（「追加の記録あり」）。write_transaction の内側で、
    結果の保存と一緒に呼ぶ。この後に `take_regen_pending` が次の回を始める。
    """
    conn.execute(
        "UPDATE visits SET status = 'generating' WHERE id = ? AND status = 'ready'"
        " AND regen_pending = 1 AND regen_count < ?",
        (vid, REGEN_AUTO_MAX),
    )


def take_regen_pending(
    conn: sqlite3.Connection, vid: int, *, counted: bool = True
) -> bool:
    """生成の終わりに、待っている分があれば下ろして generating にし True を返す。

    生成を回している側（`visit.run_generation`）だけが呼ぶ。閉じた受診・待っていない受診・
    回数を使い切った受診は何も変えずに False。counted=False は regen_count を足さない
    （Claude を呼ばない回収の周回）。
    """
    start = _START_AUTO if counted else _START_UNCOUNTED
    with write_transaction(conn):
        cur = conn.execute(
            start + " AND regen_pending = 1",
            (vid, dt_to_db(clock_now()), REGEN_AUTO_MAX),
        )
    return cur.rowcount > 0


def clear_regen_pending(conn: sqlite3.Connection, vid: int) -> None:
    """生成中の受診の待っている分を下ろす（`api.orphans` が回収の前に呼ぶ）。

    回収はこの後に全ての記録を読むので、ここまでに届いた分のために回し直さなくてよい。
    生成中でなければ何も変えない。
    """
    with write_transaction(conn):
        conn.execute(
            "UPDATE visits SET regen_pending = 0 WHERE id = ? AND status = 'generating'",
            (vid,),
        )

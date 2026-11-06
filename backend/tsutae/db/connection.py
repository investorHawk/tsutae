"""接続・スキーマ適用と、各リポジトリ共通の変換ヘルパ。

日時は JST に直し、マイクロ秒まで固定幅の ISO 8601（`+09:00` 付き）で保存する。
固定幅にしておくと文字列の比較・並べ替えが時刻の順と一致する。

接続の共有について（重要）:
- sqlite3 のトランザクションは接続ごとに1つ。1本の接続を複数スレッドで共有すると、
  並行トランザクションが混ざる（あるスレッドの commit が、別スレッドの書きかけの
  文までまとめて確定させる）
- そのため本パッケージの書き込みは全て `write_transaction` を通し、プロセス内の
  ロックで直列化している。ただし呼び出し側が `conn.execute` で直接書いた未コミット
  の文は守れない（次の書き込み関数の commit で一緒に確定する）。直接書かないこと
- 推奨は「リクエスト・タスクごとに `connect` する」こと（安い）。別接続どうしは
  WAL と busy_timeout で待ち合わせる
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from tsutae.config import JST

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
MEMORY = ":memory:"
BUSY_TIMEOUT_MS = 5000

# 書き込みトランザクションをプロセス内で直列化する（共有接続での混線を防ぐ）。
# 再入可能にしておく（書き込み関数の中から別の書き込み関数を呼んでも止まらない）。
_WRITE_LOCK = threading.RLock()


class NotFoundError(LookupError):
    """指定した患者・受診・変更依頼などが無い。"""


class VisitClosedError(ValueError):
    """印刷済み・期限切れ（受付番号を消した）受診に、変換結果やレポートを書こうとした。"""


class VisitAlreadyPrintedError(ValueError):
    """その患者に今日の印刷済みの受診があるのに、受付に記録が届いた（何も保存しない）。"""


def connect(path: Path) -> sqlite3.Connection:
    """SQLite に接続する。

    row_factory=Row、foreign_keys ON、busy_timeout、secure_delete ON（消した行の中身を
    ゼロで上書きする）、ファイルなら journal_mode=WAL。
    check_same_thread=False だが、共有するときはモジュール冒頭の注意を読むこと。
    """
    if str(path) != MEMORY:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path), check_same_thread=False, timeout=BUSY_TIMEOUT_MS / 1000
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_MS)}")
    conn.execute(
        "PRAGMA secure_delete = ON"
    )  # 消した行（期限切れのレポート等）を残さない
    if str(path) != MEMORY:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def write_lock() -> Iterator[None]:
    """書き込みのプロセス内ロックだけを握る（トランザクションは呼び出し側が開く）。"""
    with _WRITE_LOCK:
        yield


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """書き込み用のトランザクション。ロックの内側で `with conn:` を開く。

    例外なら rollback してからロックを放す。正常なら commit してから放す。
    """
    with _WRITE_LOCK, conn:
        yield conn


def init_db(conn: sqlite3.Connection) -> None:
    """古い形の表を作り直してから（`migrate.migrate_db`）schema.sql を流し、既存の
    entries から日付の印を作る（`backfill_record_marks`。表ができた後でないと書けない）。

    schema.sql は CREATE ... IF NOT EXISTS のみ、移行も新しい形なら何もしないので、
    何度呼んでもよい。
    """
    from tsutae.db.migrate import migrate_db  # migrate は SCHEMA_PATH をここから引く
    from tsutae.db.repo_record_marks import backfill_record_marks

    migrate_db(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    backfill_record_marks(conn)


def to_jst(value: datetime) -> datetime:
    """tz-aware を JST に直す。naive は JST とみなす（config.to_jst_date と同じ）。"""
    if not isinstance(value, datetime):
        raise TypeError("datetime が必要")
    if value.tzinfo is None:
        return value.replace(tzinfo=JST)
    return value.astimezone(JST)


def dt_to_db(value: datetime) -> str:
    return to_jst(value).isoformat(timespec="microseconds")


def dt_from_db(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(JST)


def date_to_db(value: date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("date が必要")
    return value.isoformat()


def date_from_db(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def placeholders(count: int) -> str:
    """`IN (...)` 用の `?, ?, ?`。値は必ずパラメータで渡す。"""
    return ", ".join("?" for _ in range(count))


def require_exists(
    conn: sqlite3.Connection, table: str, key: object, label: str
) -> None:
    """行が無ければ NotFoundError。table は内部の固定値だけを渡す。"""
    if table not in _ID_TABLES:
        raise ValueError(f"unknown table: {table}")
    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (key,)).fetchone()
    if row is None:
        raise NotFoundError(f"{label} not found")


_ID_TABLES = frozenset({"patients", "visits", "skill_changes"})

"""Skill ごとの承認・却下の排他（プロセス間）。

Skill のディレクトリ（`<skills_dir>/<name>/`）を開いた fd に `fcntl.flock` を掛ける。
ディレクトリの inode は SKILL.md の `os.replace` で変わらないので、ロック用の
ファイルを置かずに済む（Skill のディレクトリには SKILL.md だけを置く）。
flock は開いたファイルごとのロックなので、同じプロセスの別スレッドとも排他になる。
プロセスが落ちればロックは OS が外す。

待つのは `LOCK_TIMEOUT_S` 秒まで（HTTP の要求の中で長く止まらない）。取れなければ
`SkillChangeError("busy")`（409。変更は pending のまま。やり直せる）。
"""

from __future__ import annotations

import fcntl
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tsutae.skillchange.errors import SkillChangeError

__all__ = ["LOCK_TIMEOUT_S", "skill_lock"]

LOCK_TIMEOUT_S = 3.0
_POLL_S = 0.05
_THREAD_LOCK = threading.RLock()  # flock の内側で念のため（同じプロセスの直列化）


def _open_dir(skill_dir: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        return os.open(skill_dir, flags)
    except FileNotFoundError as exc:
        raise SkillChangeError("unknown_skill") from exc
    except OSError as exc:
        raise SkillChangeError("lock_error") from exc


def _acquire(fd: int, timeout_s: float) -> None:
    deadline = time.monotonic() + max(timeout_s, 0.0)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise SkillChangeError("busy") from None
            time.sleep(_POLL_S)
        except OSError as exc:
            raise SkillChangeError("lock_error") from exc


@contextmanager
def skill_lock(skill_dir: Path, timeout_s: float | None = None) -> Iterator[None]:
    """Skill のディレクトリの排他ロックを握る間だけ中を実行する。"""
    fd = _open_dir(Path(skill_dir))
    try:
        _acquire(fd, LOCK_TIMEOUT_S if timeout_s is None else timeout_s)
        try:
            with _THREAD_LOCK:
                yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

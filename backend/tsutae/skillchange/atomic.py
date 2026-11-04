"""SKILL.md の原子的な書き込み（D4 の承認・レジメンの採用が共有する）。"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

__all__ = ["write_atomic"]


def write_atomic(path: Path, data: bytes) -> None:
    """同じディレクトリの一時ファイルに書いてから os.replace で置き換える。"""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

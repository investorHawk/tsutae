"""記録の版の質問集を引く（患者 API の共通部品）。承認済みの質問文だけで、変換結果は読まない。"""

from __future__ import annotations

import re
import sqlite3

from tsutae import db
from tsutae.schemas import Question

__all__ = ["version_questions"]

_VERSION_RE = re.compile(r"(?P<name>[a-z0-9][a-z0-9-]*)@(?P<version>[1-9][0-9]{0,8})")


def version_questions(
    conn: sqlite3.Connection, skill_version: str
) -> list[Question] | None:
    """その版の質問集。版の形が違う・登録されていない・regimen でなければ None。"""
    match = _VERSION_RE.fullmatch(skill_version)
    if match is None:
        return None
    row = db.get_skill_version(conn, match["name"], int(match["version"]))
    if row is None or row["questions"] is None:
        return None
    return list(row["questions"])

"""Skill の変更依頼（skill_changes）と版のスナップショット（skill_versions）。

skill_versions は「その日の記録に使った質問集」を後から引くためのもので、
一度保存した版は書き換えない（同じ内容の再保存は何もしない）。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from tsutae.config import now as clock_now
from tsutae.db.connection import (
    NotFoundError,
    dt_from_db,
    dt_to_db,
    placeholders,
    write_transaction,
)
from tsutae.schemas import Question

CHANGE_STATUSES = ("pending", "approved", "rejected", "failed")
_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")
_CHANGE_COLUMNS = (
    "id, skill_name, requested_text, diff, new_text, base_version, new_version,"
    " status, error_code, created_at, decided_at"
)
_UPDATABLE = ("diff", "new_text", "new_version", "status", "error_code", "decided_at")


def _validate_name(skill_name: str) -> None:
    if not isinstance(skill_name, str) or not _NAME_PATTERN.fullmatch(skill_name):
        raise ValueError(f"bad skill_name: {skill_name!r}")


def _validate_version(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} は1以上の整数")


def _validate_change_status(status: str) -> None:
    if status not in CHANGE_STATUSES:
        raise ValueError(f"unknown skill change status: {status!r}")


def _change_row(row: sqlite3.Row) -> dict[str, Any]:
    item: dict[str, Any] = dict(row)
    item["created_at"] = dt_from_db(row["created_at"])
    item["decided_at"] = dt_from_db(row["decided_at"])
    return item


def create_skill_change(
    conn: sqlite3.Connection,
    skill_name: str,
    requested_text: str,
    base_version: int,
    *,
    diff: str | None = None,
    new_text: str | None = None,
    status: str = "pending",
    error_code: str | None = None,
) -> int:
    """医師の一文による変更依頼を作り、id を返す。"""
    _validate_name(skill_name)
    if not isinstance(requested_text, str) or not requested_text.strip():
        raise ValueError("requested_text が空")
    _validate_version("base_version", base_version)
    _validate_change_status(status)
    with write_transaction(conn):
        cur = conn.execute(
            "INSERT INTO skill_changes (skill_name, requested_text, diff, new_text,"
            " base_version, status, error_code, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                skill_name,
                requested_text,
                diff,
                new_text,
                base_version,
                status,
                error_code,
                dt_to_db(clock_now()),
            ),
        )
    return int(cur.lastrowid)


def get_skill_change(conn: sqlite3.Connection, change_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_CHANGE_COLUMNS} FROM skill_changes WHERE id = ?", (change_id,)
    ).fetchone()
    return None if row is None else _change_row(row)


def list_skill_changes(
    conn: sqlite3.Connection,
    skill_name: str | None = None,
    statuses: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """変更依頼を id 昇順で返す。skill_name・statuses で絞れる。"""
    clauses: list[str] = []
    params: list[object] = []
    if skill_name is not None:
        clauses.append("skill_name = ?")
        params.append(skill_name)
    if statuses is not None:
        wanted = tuple(statuses)
        for status in wanted:
            _validate_change_status(status)
        if not wanted:
            return []
        clauses.append(f"status IN ({placeholders(len(wanted))})")
        params.extend(wanted)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT {_CHANGE_COLUMNS} FROM skill_changes{where} ORDER BY id",
        tuple(params),
    ).fetchall()
    return [_change_row(r) for r in rows]


def _clean_update(fields: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(fields) - set(_UPDATABLE))
    if unknown:
        raise ValueError(f"更新できない列: {', '.join(unknown)}")
    cleaned = dict(fields)
    if "status" in cleaned:
        _validate_change_status(cleaned["status"])
    if cleaned.get("new_version") is not None:
        _validate_version("new_version", cleaned["new_version"])
    if cleaned.get("decided_at") is not None:
        cleaned["decided_at"] = dt_to_db(cleaned["decided_at"])
    return cleaned


def update_skill_change(
    conn: sqlite3.Connection, change_id: int, **fields: Any
) -> None:
    """diff・new_text・new_version・status・error_code・decided_at を更新する。"""
    cleaned = _clean_update(fields)
    if get_skill_change(conn, change_id) is None:
        raise NotFoundError("skill change not found")
    if not cleaned:
        return
    names = [name for name in _UPDATABLE if name in cleaned]
    assignments = ", ".join(f"{name} = ?" for name in names)
    with write_transaction(conn):
        conn.execute(
            f"UPDATE skill_changes SET {assignments} WHERE id = ?",
            (*(cleaned[name] for name in names), change_id),
        )


# ---------------------------------------------------------------------------
# skill_versions
# ---------------------------------------------------------------------------

_VERSION_COLUMNS = "skill_name, version, content, questions_json, approved_at"


def _questions_to_db(questions: list[Question] | None) -> str | None:
    if questions is None:
        return None
    items = [Question.model_validate(q).model_dump() for q in questions]
    return json.dumps(items, ensure_ascii=False)


def _version_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["questions_json"]
    questions = (
        None if raw is None else [Question.model_validate(q) for q in json.loads(raw)]
    )
    return {
        "skill_name": row["skill_name"],
        "version": row["version"],
        "content": row["content"],
        "questions": questions,
        "approved_at": dt_from_db(row["approved_at"]),
    }


def insert_skill_version_row(
    conn: sqlite3.Connection,
    skill_name: str,
    version: int,
    content: str,
    questions: list[Question] | None,
    *,
    approved_at: datetime | None = None,
) -> None:
    """版を1つ入れる。呼び出し側で write_transaction を開くこと（D4 の採用が同じ
    トランザクションで regimen_forms も書くため）。

    既にあれば同じ内容なら何もしない、違えば ValueError。
    """
    _validate_name(skill_name)
    _validate_version("version", version)
    if not isinstance(content, str):
        raise ValueError("content は文字列")
    questions_json = _questions_to_db(questions)
    conn.execute(
        f"INSERT INTO skill_versions ({_VERSION_COLUMNS}) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (skill_name, version) DO NOTHING",
        (
            skill_name,
            version,
            content,
            questions_json,
            dt_to_db(approved_at if approved_at is not None else clock_now()),
        ),
    )
    row = conn.execute(
        "SELECT content, questions_json FROM skill_versions"
        " WHERE skill_name = ? AND version = ?",
        (skill_name, version),
    ).fetchone()
    if row["content"] != content or row["questions_json"] != questions_json:
        raise ValueError(f"{skill_name}@{version} は既に別の内容で保存されている")


def save_skill_version(
    conn: sqlite3.Connection,
    skill_name: str,
    version: int,
    content: str,
    questions: list[Question] | None,
    *,
    approved_at: datetime | None = None,
) -> None:
    """版のスナップショットを保存する。既にあれば同じ内容なら何もしない、違えば ValueError。"""
    _validate_name(skill_name)
    _validate_version("version", version)
    if not isinstance(content, str):
        raise ValueError("content は文字列")
    with write_transaction(conn):
        insert_skill_version_row(
            conn, skill_name, version, content, questions, approved_at=approved_at
        )


def get_skill_version(
    conn: sqlite3.Connection, skill_name: str, version: int
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM skill_versions"
        " WHERE skill_name = ? AND version = ?",
        (skill_name, version),
    ).fetchone()
    return None if row is None else _version_row(row)


def latest_skill_version(
    conn: sqlite3.Connection, skill_name: str
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM skill_versions WHERE skill_name = ?"
        " ORDER BY version DESC LIMIT 1",
        (skill_name,),
    ).fetchone()
    return None if row is None else _version_row(row)

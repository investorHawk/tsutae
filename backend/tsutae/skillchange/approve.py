"""Skill の変更の承認・却下（D4）。docs/architecture.md §9b。

排他: 承認・却下は Skill のディレクトリへの flock（`lock.skill_lock`、プロセス間）の
内側で行い、ロックを取ってから変更の行と本体の SKILL.md を読み直す。取れなければ busy。

承認の手順（ロックの内側）:
0. regimen-* は use_regimen_editor で failed にする（v1.1。T95 より前に作られた pending の
   行。旧 D4 で上げた版には form JSON が無く D4 レジメンの画面で開けない。却下はできる）
1. 変更が pending で diff・new_text があること。final = new_text の version を base+1 に
2. 本体を読む。「既に final になっている」なら途中で落ちた承認の続き（resume）とみなす
   （他の承認済みの変更が同じ版を作っていれば stale）。そうでなければ、今の版が
   base_version で、今の本文から作った差分が保存した diff と同じこと（違えば stale）
3. skill_versions に base+1 が別の内容で既にあれば、本体に触る前に version_conflict
4. 本体へ原子的に書く（同じディレクトリの一時ファイル → os.replace）
5. save_skill_version。失敗したら、本体が**自分の書いた内容のときだけ**元に戻す
6. 条件付き UPDATE で approved（pending でなくなっていれば not_pending。版は保存済み
   なので本体はそのまま。本体と skill_versions を食い違わせない）

4〜6 の間で落ちても、変更は pending のまま残り、もう一度の承認で 2 の resume から
approved まで進む（save_skill_version は同じ内容なら何もしない）。git commit はしない。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tsutae import db
from tsutae.config import now
from tsutae.pipeline.logs import EventLogger, PipelineLogger
from tsutae.schemas import RegimenSkill, ReportFormatSkill
from tsutae.skillchange.atomic import write_atomic as _write_atomic
from tsutae.skillchange.diff import set_version, unified
from tsutae.skillchange.errors import USE_REGIMEN_EDITOR, SkillChangeError
from tsutae.skillchange.lock import skill_lock
from tsutae.skillchange.state import RUN_KIND, fail_pending, transition
from tsutae.skills import (
    REGIMEN_PREFIX,
    SKILL_FILE_NAME,
    SkillValidationError,
    is_valid_skill_name,
    skill_path,
    validate_skill_text,
)

__all__ = ["approve_change", "reject_change"]


def _skill_file(name: object, skills_home: Path) -> Path:
    if not is_valid_skill_name(name):
        raise SkillChangeError("invalid_name")
    try:
        return skill_path(str(name), Path(skills_home) / ".claude" / "skills")
    except SkillValidationError as exc:
        raise SkillChangeError("invalid_name") from exc


def _pending(conn: sqlite3.Connection, change_id: object) -> dict[str, Any]:
    if isinstance(change_id, bool) or not isinstance(change_id, int):
        raise SkillChangeError("not_found")
    change = db.get_skill_change(conn, change_id)
    if change is None:
        raise SkillChangeError("not_found")
    if change["status"] != "pending":
        raise SkillChangeError("not_pending")
    return change


def _ready(conn: sqlite3.Connection, change_id: object) -> dict[str, Any]:
    change = _pending(conn, change_id)
    if change["new_text"] is None or change["diff"] is None:
        raise SkillChangeError("not_ready")
    return change


def _read_current(path: Path, name: str) -> tuple[bytes, str, int]:
    """本体のバイト列・本文（改行を \\n に揃えたもの）・版。"""
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        return raw, text, validate_skill_text(name, text).version
    except FileNotFoundError as exc:
        raise SkillChangeError("unknown_skill") from exc
    except (OSError, UnicodeDecodeError, SkillValidationError) as exc:
        raise SkillChangeError("base_invalid") from exc


def _validated(name: str, text: str) -> RegimenSkill | ReportFormatSkill:
    try:
        return validate_skill_text(name, text)
    except SkillValidationError as exc:
        raise SkillChangeError(exc.code) from exc


def _resumable(
    conn: sqlite3.Connection, change: dict[str, Any], current: str, final: str
) -> bool:
    """本体が既に final なのは、この変更の承認が途中で落ちたためか。"""
    if current != final:
        return False
    version = change["base_version"] + 1
    others = db.list_skill_changes(conn, change["skill_name"], ("approved",))
    if any(c["id"] != change["id"] and c["new_version"] == version for c in others):
        raise SkillChangeError("stale")  # 同じ本文を別の変更が承認した
    saved = db.get_skill_version(conn, change["skill_name"], version)
    if saved is not None and saved["content"] != final:
        raise SkillChangeError("version_conflict")
    return True


def _check_fresh(change: dict[str, Any], current: str, version: int) -> None:
    name = change["skill_name"]
    diff = unified(current, change["new_text"], path=f"{name}/{SKILL_FILE_NAME}")
    if version != change["base_version"] or diff != change["diff"]:
        raise SkillChangeError("stale")


def _check_no_conflict(
    conn: sqlite3.Connection, name: str, version: int, final: str
) -> None:
    saved = db.get_skill_version(conn, name, version)
    if saved is not None and saved["content"] != final:
        raise SkillChangeError("version_conflict")


def _rollback(path: Path, raw: bytes, written: bytes, logger: EventLogger) -> None:
    """本体が自分の書いた内容のときだけ raw に戻す（他の書き手の内容は消さない）。"""
    try:
        if path.read_bytes() != written:
            logger.event("rollback_skipped")
            return
        _write_atomic(path, raw)
        logger.event("rollback_done")
    except OSError:
        logger.event("rollback_failed")


def _record(
    conn: sqlite3.Connection,
    name: str,
    version: int,
    final: str,
    skill: RegimenSkill | ReportFormatSkill,
) -> None:
    questions = list(skill.questions) if isinstance(skill, RegimenSkill) else None
    try:
        db.save_skill_version(conn, name, version, final, questions)
    except (ValueError, sqlite3.Error) as exc:
        raise SkillChangeError("version_conflict") from exc


def _write_and_record(
    conn: sqlite3.Connection,
    change: dict[str, Any],
    path: Path,
    logger: EventLogger,
) -> int:
    name, version = change["skill_name"], change["base_version"] + 1
    final = set_version(change["new_text"], version)
    skill = _validated(name, final)
    raw, current, current_version = _read_current(path, name)
    if _resumable(conn, change, current, final):
        logger.event("skill_change_resume")
        _record(conn, name, version, final, skill)
        return version
    _check_fresh(change, current, current_version)
    _check_no_conflict(conn, name, version, final)
    written = final.encode("utf-8")
    try:
        _write_atomic(path, written)
    except OSError as exc:
        raise SkillChangeError("write_error") from exc
    try:
        _record(conn, name, version, final, skill)
    except SkillChangeError:
        _rollback(path, raw, written, logger)
        raise
    return version


def _mark_approved(conn: sqlite3.Connection, change_id: int, version: int) -> bool:
    return transition(
        conn, change_id, status="approved", new_version=version, decided_at=now()
    )


def _approve_locked(
    conn: sqlite3.Connection, change_id: int, path: Path, logger: EventLogger
) -> int:
    change = _ready(conn, change_id)  # ロックを取ってから読み直す
    try:
        if str(change["skill_name"]).startswith(REGIMEN_PREFIX):
            raise SkillChangeError(USE_REGIMEN_EDITOR)
        version = _write_and_record(conn, change, path, logger)
    except SkillChangeError as exc:
        fail_pending(conn, logger, change_id, exc.code)
        raise
    if not _mark_approved(conn, change_id, version):
        logger.event("decided_elsewhere", decision="approved")
        raise SkillChangeError("not_pending")
    return version


def approve_change(
    conn: sqlite3.Connection, change_id: int, *, skills_home: Path
) -> int:
    """pending の変更を本体に書き、新しい版を返す。失敗は failed にして SkillChangeError。

    ロックが取れない（busy）・決着済み（not_pending）・未完成（not_ready）は
    状態を変えない。
    """
    change = _ready(conn, change_id)
    path = _skill_file(change["skill_name"], skills_home)
    logger = PipelineLogger(conn, RUN_KIND, change_id)
    with skill_lock(path.parent):
        version = _approve_locked(conn, change_id, path, logger)
    logger.event("skill_change_approved")
    return version


def reject_change(
    conn: sqlite3.Connection, change_id: int, *, skills_home: Path | None = None
) -> None:
    """pending の変更を rejected にする（本体には触らない）。

    skills_home があれば承認と同じロックを取る（承認の途中で却下しない）。
    """
    change = _pending(conn, change_id)
    if skills_home is None:
        _reject_now(conn, change_id)
        return
    with skill_lock(_skill_file(change["skill_name"], skills_home).parent):
        _reject_now(conn, change_id)


def _reject_now(conn: sqlite3.Connection, change_id: int) -> None:
    _pending(conn, change_id)
    if not transition(conn, change_id, status="rejected", decided_at=now()):
        raise SkillChangeError("not_pending")
    PipelineLogger(conn, RUN_KIND, change_id).event("skill_change_rejected")

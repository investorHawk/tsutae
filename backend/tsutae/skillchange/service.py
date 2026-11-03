"""Skill の書き換えの依頼・承認・却下（D4）。docs/architecture.md §9b。

request_change の手順（本体の SKILL.md には触らない）:
1. 名前（SKILL_NAME_PATTERN）と依頼文を検査。今の SKILL.md を読んで版を得る
   （ここまでの失敗は行を作らず SkillChangeError）
2. skill_changes を pending で作る（diff・new_text はまだ無い。承認は not_ready で拒む）
3. 依頼文（editor.build_prompt）に二次検出 → 掛かれば failed・h1_blocked（editor を呼ばない）
4. 一時ディレクトリの `.claude/skills/<name>/SKILL.md` に写して editor を回す
   （settings.pipeline_timeout_s で打ち切り）。一時ディレクトリは必ず消す
5. 写しを読み validate_skill_text。エージェントが version を変えていれば元の版に戻して
   検査し直す → unified diff（空なら no_change）→ diff・new_text を保存
どこで失敗しても failed と短い error_code（取り消しは cancelled にしてから再送出）。

後始末: 一時ディレクトリの削除に失敗したら、書き込み権を戻して1回だけやり直す。
それでも消せなければ `temp_cleanup_failed`（`error_type:<型名>`）をログに残す
（依頼の結果は変えない。写しは SKILL.md だけで、依頼文・患者の文は置かない）。

状態の更新は `state.transition`（pending の行だけ）。依頼の途中で却下された行を
failed や diff で上書きしない。承認・却下は approve.py。

ログは PipelineLogger(conn, "skill_change", change_id)。文面（依頼文・本文・例外の
メッセージ）は入れない。例外は型名だけ（`error_type:<型名>`）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path

from claude_agent_sdk import ClaudeSDKError, ResultError

from tsutae import db
from tsutae.config import Settings
from tsutae.masking import detect_identifiers
from tsutae.pipeline.logs import EventLogger, PipelineLogger, reason_code
from tsutae.schemas import RegimenSkill, ReportFormatSkill, RunStats
from tsutae.skillchange.approve import approve_change, reject_change
from tsutae.skillchange.diff import set_version, unified
from tsutae.skillchange.editor import SkillEditor, build_prompt, logging_to
from tsutae.skillchange.errors import SkillChangeError
from tsutae.skillchange.state import RUN_KIND, fail_pending, transition
from tsutae.skills import (
    SKILL_FILE_NAME,
    SkillNotFoundError,
    SkillValidationError,
    is_valid_skill_name,
    read_skill_text,
    validate_skill_text,
)

__all__ = [
    "MAX_REQUEST_CHARS",
    "RUN_KIND",
    "approve_change",
    "reject_change",
    "request_change",
]  # approve_change・reject_change は approve.py（従来の import 先を保つ）

MAX_REQUEST_CHARS = 2000
_TEMP_PREFIX = "tsutae-skillchange-"
_CLEANUP_ATTEMPTS = 2
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------


def _skills_dir(skills_home: Path) -> Path:
    return Path(skills_home) / ".claude" / "skills"


def _diff_path(name: str) -> str:
    return f"{name}/{SKILL_FILE_NAME}"


def _check_name(skill_name: object) -> str:
    if not is_valid_skill_name(skill_name):
        raise SkillChangeError("invalid_name")
    return str(skill_name)


def _check_request(request_text: object) -> str:
    if (
        not isinstance(request_text, str)
        or not request_text.strip()
        or len(request_text) > MAX_REQUEST_CHARS
    ):
        raise SkillChangeError("invalid_request")
    return request_text


def _validated(name: str, text: str) -> RegimenSkill | ReportFormatSkill:
    try:
        return validate_skill_text(name, text)
    except SkillValidationError as exc:
        raise SkillChangeError(exc.code) from exc


# ---------------------------------------------------------------------------
# request_change
# ---------------------------------------------------------------------------


def _read_base(name: str, skills_dir: Path) -> tuple[str, int]:
    try:
        text = read_skill_text(name, skills_dir)
    except SkillNotFoundError as exc:
        raise SkillChangeError("unknown_skill") from exc
    except SkillValidationError as exc:
        raise SkillChangeError("base_invalid") from exc
    try:
        return text, validate_skill_text(name, text).version
    except SkillValidationError as exc:
        raise SkillChangeError("base_invalid") from exc


def _editor_error_code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ResultError) and (
        "max_turns" in (exc.subtype or "") or exc.terminal_reason == "max_turns"
    ):
        return "max_turns"
    return "sdk_error" if isinstance(exc, ClaudeSDKError) else "editor_error"


async def _run_editor(
    editor: SkillEditor,
    work_root: Path,
    name: str,
    request_text: str,
    settings: Settings,
    logger: EventLogger,
) -> RunStats:
    logger.event("editor_start")
    try:
        with logging_to(logger):
            stats = await asyncio.wait_for(
                editor.edit(work_root, name, request_text), settings.pipeline_timeout_s
            )
    except Exception as exc:  # 取り消し（CancelledError）は通す
        logger.event(
            "editor_error", decision=reason_code("error_type", type(exc).__name__)
        )
        raise SkillChangeError(_editor_error_code(exc)) from exc
    if isinstance(stats, RunStats):
        logger.event("editor_done", **stats.model_dump(exclude={"num_turns"}))
    else:
        logger.event("editor_done")
    return stats


def _read_copy(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise SkillChangeError("missing_output")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillChangeError("format") from exc
    except OSError as exc:
        raise SkillChangeError("missing_output") from exc


def _checked_new_text(name: str, new: str, base: int) -> str:
    """検査済みで、version を base に揃えた新しい本文。

    承認の時に set_version で版を上げられない形（引用符つきのキー・flow 形式など）は
    ここで version_line にする（pending になってから承認で失敗させない）。
    """
    result = new
    if _validated(name, new).version != base:
        result = set_version(new, base)
        if _validated(name, result).version != base:  # set_version の後は起きない
            raise SkillChangeError("version_line")
    set_version(result, base + 1)  # 試すだけ（承認で同じ書き換えをする）
    return result


async def _edit_in_copy(
    name: str,
    old: str,
    request_text: str,
    *,
    editor: SkillEditor,
    settings: Settings,
    logger: EventLogger,
) -> str:
    """一時ディレクトリの写しを editor に直させ、新しい本文を返す。"""
    work_root = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX)).resolve()
    try:
        copy = work_root / ".claude" / "skills" / name / SKILL_FILE_NAME
        copy.parent.mkdir(parents=True)
        with open(copy, "w", encoding="utf-8", newline="") as f:
            f.write(old)
        await _run_editor(editor, work_root, name, request_text, settings, logger)
        return _read_copy(copy)
    finally:
        _remove_tree(work_root, logger)


def _make_writable(root: Path) -> None:
    """root の下のディレクトリに持ち主の rwx を戻す（リンクはたどらない）。"""
    for dirpath, _dirs, _files in os.walk(root):
        try:
            mode = stat.S_IMODE(os.lstat(dirpath).st_mode)
            os.chmod(dirpath, mode | stat.S_IRWXU)
        except OSError:
            continue


def _remove_tree(root: Path, logger: EventLogger) -> bool:
    """一時ディレクトリを消す。失敗は権限を戻して再試行し、それでも駄目ならログに残す。"""
    error: OSError | None = None
    for _ in range(_CLEANUP_ATTEMPTS):
        try:
            shutil.rmtree(root)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            error = exc
            _make_writable(root)
    code = reason_code("error_type", type(error).__name__)
    logger.event("temp_cleanup_failed", decision=code)
    _log.warning("skillchange temp_cleanup_failed %s", code)
    return False


def _check_h1(name: str, request_text: str, logger: EventLogger) -> None:
    found = detect_identifiers(build_prompt(name, request_text))
    if found:
        logger.event(
            "h1_check", hook_name="H1", decision=reason_code("block", found[0].rule)
        )
        raise SkillChangeError("h1_blocked")
    logger.event("h1_check", hook_name="H1", decision="allow")


async def _produce_diff(
    name: str,
    old: str,
    base: int,
    request_text: str,
    *,
    editor: SkillEditor,
    settings: Settings,
    logger: EventLogger,
) -> tuple[str, str]:
    _check_h1(name, request_text, logger)
    edited = await _edit_in_copy(
        name, old, request_text, editor=editor, settings=settings, logger=logger
    )
    new = _checked_new_text(name, edited, base)
    diff = unified(old, new, path=_diff_path(name))
    if not diff:
        raise SkillChangeError("no_change")
    return diff, new


async def request_change(
    conn: sqlite3.Connection,
    skill_name: str,
    request_text: str,
    *,
    editor: SkillEditor,
    settings: Settings,
    skills_home: Path,
) -> int:
    """書き換えを依頼し、skill_changes の id を返す（pending か failed）。"""
    name = _check_name(skill_name)
    text = _check_request(request_text)
    old, base = _read_base(name, _skills_dir(skills_home))
    change_id = db.create_skill_change(conn, name, text, base)
    logger = PipelineLogger(conn, RUN_KIND, change_id)
    logger.event("skill_change_request")
    try:
        diff, new = await _produce_diff(
            name, old, base, text, editor=editor, settings=settings, logger=logger
        )
    except SkillChangeError as exc:
        fail_pending(conn, logger, change_id, exc.code)
        return change_id
    except asyncio.CancelledError:
        fail_pending(conn, logger, change_id, "cancelled")
        raise
    if transition(conn, change_id, diff=diff, new_text=new):
        logger.event("skill_change_pending")
    else:
        logger.event("decided_elsewhere", decision="pending")
    return change_id

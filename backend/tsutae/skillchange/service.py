"""Skill の書き換えの依頼・承認・却下（D4）。docs/architecture.md §9b。

request_change の手順（本体の SKILL.md には触らない）:
1. 名前（SKILL_NAME_PATTERN）と依頼文を検査。今の SKILL.md を読んで版を得る。
   同じ Skill に作業中（pending・diff なし）の行があれば busy（created_at から
   settings.pipeline_timeout_s を過ぎた作業中の行は先に failed・stale_request にする）
   （ここまでの失敗は行を作らず SkillChangeError）
2. skill_changes を pending で作る（diff・new_text はまだ無い。承認は not_ready で拒む）
3. 依頼文（editor.build_prompt）に二次検出 → 掛かれば failed・h1_blocked（editor を呼ばない）
4. 一時ディレクトリの `.claude/skills/<name>/SKILL.md` に写して editor を回す
   （settings.pipeline_timeout_s で打ち切り）。一時ディレクトリは必ず消す
5. 写しを読み validate_skill_text。エージェントが version を変えていれば元の版に戻して
   検査し直す → unified diff（空なら no_change）→ diff・new_text を保存
どこで失敗しても failed と短い error_code（取り消しは cancelled にしてから再送出）。
editor の SDK の失敗は `sdk_error_code` で max_budget / max_turns / sdk_error（費用・
トークン数は editor が `editor_failed` に残す）。
行を作った後の一時ディレクトリの作成・写しの失敗（OSError）は `workdir_error`。

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

from claude_agent_sdk import ClaudeSDKError

from tsutae import db
from tsutae.config import Settings
from tsutae.masking import detect_identifiers
from tsutae.pipeline.logs import EventLogger, PipelineLogger, reason_code
from tsutae.pipeline.orchestrator import sdk_error_code
from tsutae.pipeline.runner import RunFailedError
from tsutae.schemas import RegimenSkill, ReportFormatSkill, RunStats
from tsutae.skillchange.approve import approve_change, reject_change
from tsutae.skillchange.check import baseline_of, identifier_like_question
from tsutae.skillchange.diff import set_version, unified
from tsutae.skillchange.editor import SkillEditor, build_prompt, logging_to
from tsutae.skillchange.errors import SkillChangeError
from tsutae.skillchange.state import (
    RUN_KIND,
    fail_pending,
    fail_stale_requests,
    has_working,
    transition,
)
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
    "WORKDIR_ERROR",
    "approve_change",
    "reject_change",
    "request_change",
]  # approve_change・reject_change は approve.py（従来の import 先を保つ）

MAX_REQUEST_CHARS = 2000
# 一時ディレクトリの作成・写しの書き込み（mkdtemp・mkdir・open）の OSError の error_code
WORKDIR_ERROR = "workdir_error"
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
    # max_budget / max_turns / sdk_error（RunFailedError は中身で判定。pipeline と同じ）
    return sdk_error_code(exc) if isinstance(exc, ClaudeSDKError) else "editor_error"


def _error_type(exc: BaseException) -> str:
    """ログに残す型名（RunFailedError は包む前の例外の型）。"""
    cause = exc.cause if isinstance(exc, RunFailedError) else exc
    return type(cause).__name__


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
            "editor_error", decision=reason_code("error_type", _error_type(exc))
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
    if identifier_like_question(_validated(name, new)) is not None:
        raise SkillChangeError("identifier_like")
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
    try:
        work_root = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX)).resolve()
    except OSError as exc:
        raise _workdir_error(exc, logger) from exc
    try:
        copy = _write_copy(work_root, name, old, logger)
        await _run_editor(editor, work_root, name, request_text, settings, logger)
        return _read_copy(copy)
    finally:
        _remove_tree(work_root, logger)


def _write_copy(work_root: Path, name: str, old: str, logger: EventLogger) -> Path:
    """work_root の `.claude/skills/<name>/SKILL.md` に今の本文を写し、その場所を返す。"""
    copy = work_root / ".claude" / "skills" / name / SKILL_FILE_NAME
    try:
        copy.parent.mkdir(parents=True)
        with open(copy, "w", encoding="utf-8", newline="") as f:
            f.write(old)
    except OSError as exc:
        raise _workdir_error(exc, logger) from exc
    return copy


def _workdir_error(exc: OSError, logger: EventLogger) -> SkillChangeError:
    """一時ディレクトリを作れない・写せない（行は作った後なので failed にする）。"""
    logger.event(WORKDIR_ERROR, decision=reason_code("error_type", type(exc).__name__))
    return SkillChangeError(WORKDIR_ERROR)


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


def _check_h1(name: str, old: str, request_text: str, logger: EventLogger) -> None:
    """editor が渡すのと同じ依頼文（今の質問の key を含む）に二次検出を掛ける。"""
    keys = baseline_of(name, old).question_keys
    found = detect_identifiers(build_prompt(name, request_text, question_keys=keys))
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
    _check_h1(name, old, request_text, logger)
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
    # 確かめてから行を作るまでに await を挟まない（同じイベントループの別の依頼が
    # 間に入らない。単一プロセスが前提）
    fail_stale_requests(conn, settings.pipeline_timeout_s, name)
    if has_working(conn, name):
        raise SkillChangeError("busy")
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

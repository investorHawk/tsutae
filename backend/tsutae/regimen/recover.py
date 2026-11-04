"""採用の途中で止まった下書きを起動時に補う（architecture 9c「確認と採用」）。

採用は「ファイルが先・DB が後」（approve.py と同じ）。SKILL.md を置いた後・DB の commit の
前にプロセスが落ちると、起動し直したとき `ensure_skill_versions` が SKILL.md の版を
skill_versions に登録するが、regimen_forms・部品集・下書きの adopted は無いまま残る
（既存は form_unavailable、新規は code_taken で開けなくなる）。

`recover_interrupted_adoptions(conn, skills_dir)`（起動時に ensure_skill_versions の後で呼ぶ）:

- 開いた（open の）下書きのうち、採用で作る版が skill_versions にあり regimen_forms に無い
  もの: 今の値で描いた文（`render_draft`）が登録された版の文とバイトで一致すれば、
  1つのトランザクションで regimen_forms・部品集（origin=adopted）・下書きの adopted を補う。
  一致しなければ補わず、Skill 名と版を警告に残す（別の書き手の版。先生が確かめる）
- 新規の下書きで、識別名のフォルダはあるが SKILL.md が無い（mkdir の後に止まった）もの:
  書き込みの一時ファイルだけならフォルダを消す（他のファイルがあれば残して警告）
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from tsutae import db
from tsutae.db import repo_regimen_drafts as repo
from tsutae.db.repo_question_library import insert_question_row
from tsutae.regimen.adopt import library_items, remove_new_dir
from tsutae.regimen.drafts import (
    draft_form,
    draft_skill_name,
    target_version,
)
from tsutae.regimen.form import RegimenForm
from tsutae.regimen.preview import render_draft, schedule_lock_issues
from tsutae.regimen.source import canonical_form_json
from tsutae.regimen.text_checks import RegimenFormError
from tsutae.skills import SKILL_FILE_NAME, SkillValidationError

__all__ = ["recover_interrupted_adoptions"]

_log = logging.getLogger(__name__)


class _NotOpen(Exception):
    """補う間に下書きが変わった・閉じた（書いた行を巻き戻す）。"""


class _Locked(Exception):
    """患者のいるレジメンで日程を変えている（adopt が断る版。巻き戻す）。"""


# 下書き1件の回復で出うる例外。起動を止めず、警告に残して次へ進む
_RECOVER_FAILURES: tuple[type[BaseException], ...] = (
    ValueError,  # pydantic の ValidationError・RegimenFormError・SkillValidationError を含む
    TypeError,
    KeyError,
    OSError,
    sqlite3.Error,
)


def _complete(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    form: RegimenForm,
    name: str,
    version: int,
) -> bool:
    try:
        with db.write_transaction(conn):
            repo.insert_regimen_form_row(conn, name, version, canonical_form_json(form))
            if schedule_lock_issues(conn, draft, form, name):
                raise _Locked
            for item in library_items(form):
                insert_question_row(conn, item, "adopted")
            if not repo.mark_adopted_row(
                conn,
                draft["id"],
                form_json=draft["form_json"],
                sources_json=draft["sources_json"],
                adopted_version=version,
            ):
                raise _NotOpen
    except _NotOpen:
        return False
    except _Locked:
        _log.warning(
            "regimen.recover_skipped skill=%s version=%d draft=%d reason=schedule_locked",
            name,
            version,
            draft["id"],
        )
        return False
    return True


def _clear_empty_new_dir(draft: dict[str, Any], name: str, skills_dir: Path) -> None:
    folder = Path(skills_dir) / name
    if draft["base_version"] is not None or not folder.is_dir():
        return
    if not (folder / SKILL_FILE_NAME).exists():
        remove_new_dir(folder, keep_skill=True)


def _recover_one(
    conn: sqlite3.Connection, draft: dict[str, Any], skills_dir: Path
) -> bool:
    form = draft_form(draft)
    name = draft_skill_name(draft, form)
    if name is None:
        return False
    version = target_version(draft)
    row = db.get_skill_version(conn, name, version)
    if row is None:
        _clear_empty_new_dir(draft, name, skills_dir)
        return False
    if repo.get_regimen_form(conn, name, version) is not None:
        return False
    try:
        text = render_draft(draft, form)
    except (RegimenFormError, SkillValidationError):
        text = None
    if text != row["content"]:
        _log.warning(
            "regimen.recover_mismatch skill=%s version=%d draft=%d",
            name,
            version,
            draft["id"],
        )
        return False
    if not _complete(conn, draft, form, name, version):
        return False
    _log.info("採用の途中で止まった %s@%d を補った", name, version)
    return True


def recover_interrupted_adoptions(conn: sqlite3.Connection, skills_dir: Path) -> int:
    """採用の途中で止まった下書きを補い、補った数を返す。何度呼んでもよい。"""
    count = 0
    for draft in repo.list_active_drafts(conn):
        if draft["status"] != "open":
            continue
        try:
            recovered = _recover_one(conn, draft, skills_dir)
        except _RECOVER_FAILURES as exc:
            # 入力の文面は残さない（例外の型名と下書きの id だけ）
            _log.warning(
                "regimen.recover_failed draft=%d error=%s",
                draft["id"],
                type(exc).__name__,
            )
            continue
        if recovered:
            count += 1
    return count

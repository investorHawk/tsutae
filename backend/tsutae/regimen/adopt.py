"""下書きの採用（architecture 9c「確認と採用」。spec 9.1「採用」）。

`adopt(conn, draft_id, confirm_token, ai_values_confirmed, *, skills_home, timeout_s)`:

1. 下書きが open（working は `working`、閉じていれば `not_open`）
2. 印の照合（確認の画面に出した値と今の値が違えば `token_mismatch`）。AI の値があるのに
   確かめが無ければ `ai_values_unconfirmed`
3. 検査のやり直し（`preview.adoption_issues`）。stale・schedule_locked・code_taken は
   その code、他（必須・値）は `invalid_form`（issues つき）
4. 描く（`render_regimen_skill`。strict のバリデータと frontmatter の読み戻しを含む）
5. 書く（approve.py と同じ「ファイルが先・DB が後・DB が落ちたら自分が書いた内容のときだけ
   戻す」）
   - 新規: `regimen-<code小文字>/` を `os.mkdir` で排他に作る（あれば `code_taken`）→
     SKILL.md を原子的に置く（版1。書けなければ `write_error`）。失敗したらフォルダを消す
     （SKILL.md と書き込みの一時ファイルだけ。他のファイルがあれば残して警告）
   - 既存: Skill のディレクトリのロックの内側で今の版を読み直し（違えば `stale`）、版 N+1 を
     原子的に置く。失敗したら元のバイト列に戻す
6. 1つのトランザクションで skill_versions・regimen_forms・部品集（新しい3択の質問を
   origin=adopted）・下書きを adopted に（確かめた時と同じ form・出どころのときだけ。会話の
   文面も消す）。INSERT の後に患者のいるレジメンの日程をもう一度確かめる。最後の
   UPDATE が当たらなければ読み直して `working`・`not_open`・`token_mismatch`

ファイルを書いた後・commit の前にプロセスが落ちた場合は、起動時に `regimen.recover` が補う。

採用は描いた文だけを書く（手で書いた SKILL.md は書かない）。git commit はしない。
"""

from __future__ import annotations

import hmac
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsutae import db
from tsutae.db import repo_regimen_drafts as repo
from tsutae.db.repo_question_library import (
    QuestionInputError,
    insert_question_row,
    validate_library_question,
)
from tsutae.regimen.drafts import (
    DraftError,
    draft_form,
    draft_skill_name,
    draft_sources,
    load_draft,
    reload_failure,
    require_open,
    target_version,
)
from tsutae.regimen.form import RegimenForm
from tsutae.regimen.preview import (
    adoption_issues,
    ai_values,
    confirm_token,
    render_draft,
    schedule_lock_issues,
)
from tsutae.regimen.source import canonical_form_json
from tsutae.regimen.text_checks import FieldIssue, RegimenFormError
from tsutae.schemas import RegimenSkill
from tsutae.skillchange.atomic import write_atomic
from tsutae.skillchange.errors import SkillChangeError
from tsutae.skillchange.lock import skill_lock
from tsutae.skills import (
    SKILL_FILE_NAME,
    SkillValidationError,
    skill_path,
    validate_skill_text,
)

__all__ = ["AdoptResult", "adopt", "library_items", "remove_new_dir"]

_log = logging.getLogger(__name__)

# 検査の code のうち、そのまま 409 の code にするもの（他の検査は 422 invalid_form）
_CONFLICT_CODES = ("stale", "schedule_locked", "code_taken")


@dataclass(frozen=True)
class AdoptResult:
    skill_name: str
    version: int
    regimen: str


@dataclass(frozen=True)
class _Plan:
    draft: dict[str, Any]
    form: RegimenForm
    name: str
    version: int
    text: str
    skill: RegimenSkill


def _check_confirmation(
    draft: dict[str, Any], token: object, confirmed: object
) -> None:
    form, sources = draft_form(draft), draft_sources(draft)
    expected = confirm_token(form, sources, draft["base_version"])
    # bytes で比べる（str どうしの compare_digest は ASCII 以外で TypeError を投げる）
    if not isinstance(token, str) or not hmac.compare_digest(
        token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise DraftError("token_mismatch")
    if ai_values(form, sources) and confirmed is not True:
        raise DraftError("ai_values_unconfirmed")


def _raise_issues(issues: list[FieldIssue]) -> None:
    for code in _CONFLICT_CODES:
        if any(i.code == code for i in issues):
            raise DraftError(code, [i for i in issues if i.code == code])
    raise DraftError("invalid_form", issues)


def _plan(conn: sqlite3.Connection, draft: dict[str, Any], skills_dir: Path) -> _Plan:
    form = draft_form(draft)
    issues = adoption_issues(conn, draft, form, skills_dir=skills_dir)
    if issues:
        _raise_issues(issues)
    name = draft_skill_name(draft, form) or ""
    try:
        text = render_draft(draft, form)
        skill = validate_skill_text(name, text)
    except RegimenFormError as exc:
        raise DraftError("invalid_form", exc.issues) from None
    except SkillValidationError:
        raise DraftError("render_failed") from None
    assert isinstance(skill, RegimenSkill)
    return _Plan(draft, form, name, target_version(draft), text, skill)


# ---------------------------------------------------------------------------
# DB（1つのトランザクション）
# ---------------------------------------------------------------------------


def library_items(form: RegimenForm) -> list[dict[str, str]]:
    """部品集に入れる新しい3択の質問（部品集の検査に通るものだけ。体温は入れない）。"""
    items: list[dict[str, str]] = []
    for q in form.questions:
        if q.answer_type != "three_level":
            continue
        try:
            items.append(
                validate_library_question(key=q.key, label=q.label, text=q.text)
            )
        except QuestionInputError:
            continue
    return items


def _record(conn: sqlite3.Connection, plan: _Plan) -> None:
    """版・form・部品集・下書きの adopted を1つのトランザクションで書く。

    INSERT で書き込みのトランザクションが始まる（他の接続は commit できない）ので、その後で
    患者のいるレジメンの日程をもう一度確かめる（確かめた後に患者が入った場合）。版の INSERT は
    同じ内容があれば何もしないので、必ず行を入れる regimen_forms の INSERT の後で確かめる。
    """
    draft = plan.draft
    with db.write_transaction(conn):
        try:
            db.insert_skill_version_row(
                conn, plan.name, plan.version, plan.text, list(plan.skill.questions)
            )
        except ValueError:
            raise DraftError("version_conflict") from None
        repo.insert_regimen_form_row(
            conn, plan.name, plan.version, canonical_form_json(plan.form)
        )
        locked = schedule_lock_issues(conn, draft, plan.form, plan.name)
        if locked:
            _raise_issues(locked)
        for item in library_items(plan.form):
            insert_question_row(conn, item, "adopted")
        if not repo.mark_adopted_row(
            conn,
            draft["id"],
            form_json=draft["form_json"],
            sources_json=draft["sources_json"],
            adopted_version=plan.version,
        ):  # 確かめた後に破棄・working・値が変わった
            raise reload_failure(conn, draft["id"], otherwise="token_mismatch")


# ---------------------------------------------------------------------------
# ファイル
# ---------------------------------------------------------------------------


def _own_temp_files(skill_dir: Path) -> list[Path]:
    """write_atomic の一時ファイル（`.SKILL.md.<乱数>.tmp`）。"""
    return list(skill_dir.glob(f".{SKILL_FILE_NAME}.*.tmp"))


def remove_new_dir(skill_dir: Path, *, keep_skill: bool = False) -> bool:
    """新規の採用で作ったフォルダを消す。消せたか（無ければ True）を返す。

    消すのは SKILL.md（keep_skill なら残す）と書き込みの一時ファイルだけ。他のファイルが
    あれば残し、フォルダの名前と型名を警告に残す（識別名が使えないままになるので、先生が
    手で片付ける）。
    """
    try:
        if not keep_skill:
            (skill_dir / SKILL_FILE_NAME).unlink(missing_ok=True)
        for tmp in _own_temp_files(skill_dir):
            tmp.unlink(missing_ok=True)
        skill_dir.rmdir()
    except FileNotFoundError:
        return True
    except OSError as exc:
        _log.warning(
            "regimen.adopt_cleanup_failed dir=%s error_type=%s",
            skill_dir.name,
            type(exc).__name__,
        )
        return False
    return True


def _adopt_new(conn: sqlite3.Connection, plan: _Plan, skills_dir: Path) -> None:
    path = skill_path(plan.name, skills_dir)
    try:
        os.mkdir(path.parent)
    except FileExistsError:
        raise DraftError("code_taken") from None
    try:
        with skill_lock(path.parent):
            try:
                write_atomic(path, plan.text.encode("utf-8"))
            except OSError:
                raise DraftError("write_error") from None
            _record(conn, plan)
    except BaseException:
        remove_new_dir(path.parent)
        raise


def _current_bytes(path: Path, name: str, base_version: int) -> bytes:
    try:
        raw = path.read_bytes()
        current = validate_skill_text(name, raw.decode("utf-8")).version
    except FileNotFoundError:
        raise DraftError("stale") from None
    except (OSError, UnicodeDecodeError, SkillValidationError):
        raise DraftError("base_invalid") from None
    if current != base_version:
        raise DraftError("stale")
    return raw


def _restore(path: Path, raw: bytes, written: bytes) -> None:
    """本体が自分の書いた内容のときだけ元に戻す（他の書き手の内容は消さない）。"""
    try:
        if path.read_bytes() == written:
            write_atomic(path, raw)
    except OSError:
        pass


def _adopt_existing(conn: sqlite3.Connection, plan: _Plan, skills_dir: Path) -> None:
    path = skill_path(plan.name, skills_dir)
    with skill_lock(path.parent):
        raw = _current_bytes(path, plan.name, int(plan.draft["base_version"]))
        written = plan.text.encode("utf-8")
        try:
            write_atomic(path, written)
        except OSError:
            raise DraftError("write_error") from None
        try:
            _record(conn, plan)
        except BaseException:
            _restore(path, raw, written)
            raise


def adopt(
    conn: sqlite3.Connection,
    draft_id: int,
    token: object,
    ai_values_confirmed: object,
    *,
    skills_home: Path,
    timeout_s: float,
) -> AdoptResult:
    """下書きを採用し、書いた Skill 名・版を返す。止めたら DraftError。"""
    skills_dir = Path(skills_home) / ".claude" / "skills"
    draft = load_draft(conn, draft_id, timeout_s=timeout_s)
    require_open(draft)
    _check_confirmation(draft, token, ai_values_confirmed)
    plan = _plan(conn, draft, skills_dir)
    try:
        if draft["base_version"] is None:
            _adopt_new(conn, plan, skills_dir)
        else:
            _adopt_existing(conn, plan, skills_dir)
    except SkillChangeError as exc:  # ロックが取れない（busy）など
        raise DraftError(exc.code) from None
    return AdoptResult(plan.name, plan.version, plan.skill.regimen)

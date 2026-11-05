"""D4 レジメンの下書き — 作る・読む・直接編集・破棄（architecture 9c「下書き」）。

- 新規: `create_new_draft`（体温の質問だけを持つ空のフォーム。識別名が決まるまで regimen は
  NULL）。既存: `open_skill_draft`（今の版 N の form から版 N+1 の下書き。同じレジメンに
  開いた下書きがあればそれを返す）
- 読み出しの前に `recover_stale_working`（working のまま上限を過ぎた行を open に戻す）
- `patch_draft`: 先生の直接編集（出どころ doctor_edit）。`edit.apply_patch` の検査に掛かれば
  `DraftError("invalid_fields", issues)`。新規の下書きの識別名は、既存の Skill・別の開いた
  下書きと同じなら欄の `code_taken`
- working の間の書き換え・破棄は `working`、閉じた下書きは `not_open`。読んでから書くまでに
  別の書き手（T94 の往復など）が値を変えていれば `conflict`（画面は読み直す）

失敗は全て `DraftError(code, issues)`。API が code を HTTP の状態に写す（422 は issues つき）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tsutae import db
from tsutae.db import repo_regimen_drafts as repo
from tsutae.regimen.edit import FormPatch, apply_patch
from tsutae.regimen.form import FieldSources, RegimenForm, load_form_json
from tsutae.regimen.source import (
    canonical_form_json,
    canonical_sources_json,
    form_from_skill,
    new_draft_form,
)
from tsutae.regimen.text_checks import FieldIssue, RegimenFormError
from tsutae.skills import (
    SkillNotFoundError,
    SkillValidationError,
    is_valid_skill_name,
    load_skill,
    regimen_skill_name,
)

__all__ = [
    "DraftError",
    "code_taken",
    "create_new_draft",
    "discard",
    "draft_form",
    "draft_skill_name",
    "draft_sources",
    "load_draft",
    "open_skill_draft",
    "patch_draft",
    "reload_failure",
    "require_open",
    "target_version",
]


class DraftError(Exception):
    """下書きの操作の失敗。code は短い英字、issues は欄の id と理由（422 のとき）。"""

    def __init__(self, code: str, issues: Sequence[FieldIssue] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.issues: tuple[FieldIssue, ...] = tuple(issues)


# ---------------------------------------------------------------------------
# 読み出し
# ---------------------------------------------------------------------------


def draft_form(draft: dict[str, Any]) -> RegimenForm:
    return load_form_json(draft["form_json"])


def draft_sources(draft: dict[str, Any]) -> FieldSources:
    return FieldSources.model_validate_json(draft["sources_json"])


def target_version(draft: dict[str, Any]) -> int:
    """採用で作る版（新規は1、既存は版 N+1）。"""
    base = draft["base_version"]
    return 1 if base is None else int(base) + 1


def draft_skill_name(draft: dict[str, Any], form: RegimenForm) -> str | None:
    """下書きの Skill 名（新規で識別名がまだ無ければ None）。"""
    return regimen_skill_name(draft["regimen"] or form.basic.code)


def load_draft(
    conn: sqlite3.Connection, draft_id: int, *, timeout_s: float
) -> dict[str, Any]:
    """取り残された working を戻してから1件読む。無ければ not_found。"""
    repo.recover_stale_working(conn, timeout_s=timeout_s)
    draft = repo.get_draft(conn, draft_id)
    if draft is None:
        raise DraftError("not_found")
    return draft


def require_open(draft: dict[str, Any]) -> None:
    if draft["status"] == "working":
        raise DraftError("working")
    if draft["status"] != "open":
        raise DraftError("not_open")


def reload_failure(
    conn: sqlite3.Connection, draft_id: int, *, otherwise: str
) -> DraftError:
    """条件付きの書き換えが当たらなかった理由。working・閉じた、でなければ otherwise。

    otherwise は open のまま値だけが変わっていた場合（PATCH は conflict、採用は
    token_mismatch）。
    """
    draft = repo.get_draft(conn, draft_id)
    if draft is not None and draft["status"] == "working":
        return DraftError("working")
    if draft is None or draft["status"] != "open":
        return DraftError("not_open")
    return DraftError(otherwise)


# ---------------------------------------------------------------------------
# 作る
# ---------------------------------------------------------------------------


def create_new_draft(conn: sqlite3.Connection) -> dict[str, Any]:
    draft_id = repo.create_draft(
        conn,
        regimen=None,
        base_version=None,
        form_json=canonical_form_json(new_draft_form()),
    )
    return repo.get_draft(conn, draft_id) or {}


def _current_skill(name: object, skills_dir: Path) -> Any:
    if not is_valid_skill_name(name) or not str(name).startswith("regimen-"):
        raise DraftError("invalid_name")
    try:
        return load_skill(str(name), skills_dir)
    except SkillNotFoundError:
        raise DraftError("unknown_skill") from None
    except SkillValidationError:
        raise DraftError("base_invalid") from None


def open_skill_draft(
    conn: sqlite3.Connection, skill_name: object, *, skills_dir: Path
) -> tuple[dict[str, Any], bool]:
    """既存のレジメンの版 N+1 の下書きと、新しく作ったか。開いた下書きがあればそれを返す。"""
    skill = _current_skill(skill_name, skills_dir)
    existing = repo.find_active_draft(conn, skill.regimen)
    if existing is not None:
        return existing, False
    form = form_from_skill(conn, skill.name, skill.version)
    if form is None or form.basic.code != skill.regimen:
        raise DraftError("form_unavailable")
    try:
        draft_id = repo.create_draft(
            conn,
            regimen=skill.regimen,
            base_version=skill.version,
            form_json=canonical_form_json(form),
        )
    except repo.DraftConflictError:  # 同時に作られた
        found = repo.find_active_draft(conn, skill.regimen)
        if found is None:
            raise DraftError("draft_exists") from None
        return found, False
    return repo.get_draft(conn, draft_id) or {}, True


# ---------------------------------------------------------------------------
# 直接編集・破棄
# ---------------------------------------------------------------------------


def code_taken(
    conn: sqlite3.Connection, code: str, *, skills_dir: Path, draft_id: int
) -> bool:
    """識別名が既存の Skill（フォルダ・版）か、別の開いた下書きで使われているか。"""
    name = regimen_skill_name(code)
    if name is None:
        return False
    if (Path(skills_dir) / name).exists() or db.latest_skill_version(conn, name):
        return True
    other = repo.find_active_draft(conn, code)
    return other is not None and other["id"] != draft_id


def _code_taken_issue() -> FieldIssue:
    return FieldIssue("basic.code", "code_taken", "同じ識別名のレジメンか下書きがある")


def _new_regimen(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    form: RegimenForm,
    skills_dir: Path,
) -> str | None:
    """書き換えた後の regimen の列（既存の版の下書きは変えない）。"""
    if draft["base_version"] is not None:
        return draft["regimen"]
    code = form.basic.code
    changed = bool(code) and code != draft["regimen"]
    if changed and code_taken(conn, code, skills_dir=skills_dir, draft_id=draft["id"]):
        raise DraftError("invalid_fields", [_code_taken_issue()])
    return code or None


def patch_draft(
    conn: sqlite3.Connection,
    draft_id: int,
    patch: FormPatch,
    *,
    skills_dir: Path,
    timeout_s: float,
) -> dict[str, Any]:
    """先生の直接編集を当てて保存し、新しい下書きを返す。検査に掛かれば保存しない。"""
    draft = load_draft(conn, draft_id, timeout_s=timeout_s)
    require_open(draft)
    try:
        form, sources = apply_patch(
            draft_form(draft),
            draft_sources(draft),
            patch,
            allow_code=draft["base_version"] is None,
        )
    except RegimenFormError as exc:
        raise DraftError("invalid_fields", exc.issues) from None
    regimen = _new_regimen(conn, draft, form, skills_dir)
    try:
        updated = repo.update_draft_form(
            conn,
            draft_id,
            form_json=canonical_form_json(form),
            sources_json=canonical_sources_json(sources),
            regimen=regimen,
            expected_form_json=draft["form_json"],
            expected_sources_json=draft["sources_json"],
        )
    except repo.DraftConflictError:
        raise DraftError("invalid_fields", [_code_taken_issue()]) from None
    if not updated:  # 読んでから書くまでに別の書き手が変えた・閉じた
        raise reload_failure(conn, draft_id, otherwise="conflict")
    return repo.get_draft(conn, draft_id) or {}


def discard(conn: sqlite3.Connection, draft_id: int, *, timeout_s: float) -> None:
    """下書きを捨てる（会話の文面を消す）。"""
    draft = load_draft(conn, draft_id, timeout_s=timeout_s)
    require_open(draft)
    if not repo.discard_draft(conn, draft_id):
        raise reload_failure(conn, draft_id, otherwise="not_open")

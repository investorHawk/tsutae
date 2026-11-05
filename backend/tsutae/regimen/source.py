"""下書きの元になるフォーム（architecture 9c「逆向き」）と、保存の形（正規化した JSON）。

- `new_draft_form()`: 新しいレジメンの空のフォーム。体温の質問（今の FOLFOX の temperature
  と同じ key・文・型）を初めから持つ
- `form_from_skill(conn, name, version)`: D4 で採用した版は `regimen_forms` 表、
  FOLFOX/CAPOX@1 はリポジトリの JSON。どちらも無ければ None（旧 D4 の一文で上げた版など）。
  SKILL.md を読み戻して解析はしない
- `canonical_form_json` / `canonical_sources_json`: 下書きの保存・確認の印に使う同じ形
"""

from __future__ import annotations

import json
import sqlite3

from tsutae.db.repo_regimen_drafts import get_regimen_form
from tsutae.regimen.form import (
    FieldSources,
    RegimenForm,
    load_builtin_form,
    load_form_json,
)

__all__ = [
    "BUILTIN_VERSION",
    "canonical_form_json",
    "canonical_sources_json",
    "form_from_skill",
    "new_draft_form",
]

BUILTIN_VERSION = 1
_BUILTIN_SKILLS = ("regimen-folfox", "regimen-capox")
_TEMPLATE_SKILL = "regimen-folfox"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_form_json(form: RegimenForm) -> str:
    return _canonical(form.model_dump(mode="json"))


def canonical_sources_json(sources: FieldSources) -> str:
    return _canonical(sources.root)


def new_draft_form() -> RegimenForm:
    """体温の質問だけを持つ空のフォーム（spec 9.1。38.0℃の固定規則の対象で外せない）。"""
    template = load_builtin_form(_TEMPLATE_SKILL)
    fever = next(q for q in template.questions if q.answer_type == "temperature")
    return RegimenForm(questions=[fever])


def form_from_skill(
    conn: sqlite3.Connection, skill_name: str, version: int
) -> RegimenForm | None:
    """その版の form。無ければ None。"""
    stored = get_regimen_form(conn, skill_name, version)
    if stored is not None:
        return load_form_json(stored)
    if version == BUILTIN_VERSION and skill_name in _BUILTIN_SKILLS:
        return load_builtin_form(skill_name)
    return None

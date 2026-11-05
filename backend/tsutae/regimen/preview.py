"""確認の画面（architecture 9c「確認と採用」）— AI の値・SKILL.md・患者の見本・検査・印。

- `ai_values(form, sources)`: 出どころが standard（標準の値）の欄（欄 id・表示名・値・出どころ）。
  先生の文から（doctor_text）・先生が入れた（doctor_edit）の欄は一覧に出さず、確かめも要らない
- `confirm_token(form, sources, base_version)`: 正規化した form JSON ＋ 出どころ ＋ 元の版の
  sha256。確かめはこの印に結びつく（確かめた後に値が変われば採用できない）
- `adoption_issues(conn, draft, form, *, skills_dir)`: 採用の前の検査（必須・値・識別名の重複・
  stale・患者のいるレジメンの日程）。preview は一覧に出し、adopt はやり直して止める
- `build_preview(conn, draft, *, skills_dir)`: 上をまとめ、描けるなら SKILL.md（新規は全文、
  既存は版 N との unified diff）
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from tsutae import db
from tsutae.regimen.drafts import (
    code_taken,
    draft_form,
    draft_skill_name,
    draft_sources,
    target_version,
)
from tsutae.regimen.form import FieldSources, RegimenForm, field_ids
from tsutae.regimen.render import render_regimen_skill
from tsutae.regimen.schedule import build_schedule
from tsutae.regimen.source import (
    canonical_form_json,
    canonical_sources_json,
    form_from_skill,
)
from tsutae.regimen.text_checks import FieldIssue, RegimenFormError
from tsutae.regimen.validate import validate_complete_form
from tsutae.skillchange.diff import unified
from tsutae.skills import (
    SKILL_FILE_NAME,
    SkillValidationError,
    load_skill,
    read_skill_text,
)

__all__ = [
    "AI_SOURCES",
    "adoption_issues",
    "ai_values",
    "build_preview",
    "confirm_token",
    "field_label",
    "field_value",
    "patient_preview",
    "render_draft",
    "schedule_lock_issues",
]

AI_SOURCES = frozenset({"standard"})
_FIELD_LABELS = {
    "display_name": "表示名",
    "code": "識別名",
    "target": "対象",
    "cycle_days": "1コースの日数",
    "name": "薬の名前",
    "route": "経路",
    "days": "Day",
    "times_per_day": "内服の回数",
    "start_note": "飲み始め",
    "phrases": "患者の言い方",
    "ctcae_terms": "CTCAE の用語",
    "question_key": "対応する質問",
    "key": "key",
    "label": "短い名前",
    "text": "患者に出る文",
    "answer_type": "回答の型",
}
_SECTION_LABELS = {"drugs": "薬", "side_effects": "副作用", "questions": "質問"}


# ---------------------------------------------------------------------------
# 印・AI の値・患者の見本
# ---------------------------------------------------------------------------


def confirm_token(
    form: RegimenForm, sources: FieldSources, base_version: int | None
) -> str:
    payload = "\n".join(
        (
            canonical_form_json(form),
            canonical_sources_json(sources),
            "null" if base_version is None else str(int(base_version)),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(form: RegimenForm, section: str, row_id: str) -> Any:
    rows = getattr(form, section)
    return next(r for r in rows if r.row_id == row_id)


def _row_label(section: str, row: Any) -> str:
    if section == "drugs" and row.name:
        return str(row.name)
    if section == "side_effects" and row.phrases:
        return str(row.phrases[0])
    if section == "questions" and (row.label or row.key):
        return str(row.label or row.key)
    return _SECTION_LABELS[section]


def field_label(form: RegimenForm, field_id: str) -> str:
    """欄の表示名（例:「ベバシズマブ — Day」「1コースの日数」）。"""
    parts = field_id.split(".")
    if parts == ["notes"]:
        return "補足の指示"
    if len(parts) == 2:
        return _FIELD_LABELS[parts[1]]
    section, row_id, name = parts
    row = _row(form, section, row_id)
    return f"{_row_label(section, row)} — {_FIELD_LABELS[name]}"


def field_value(form: RegimenForm, field_id: str) -> Any:
    data = form.model_dump(mode="json")
    parts = field_id.split(".")
    if len(parts) <= 2:
        node: Any = data
        for part in parts:
            node = node[part]
        return node
    section, row_id, name = parts
    return next(r for r in data[section] if r["row_id"] == row_id)[name]


def ai_values(form: RegimenForm, sources: FieldSources) -> list[dict[str, Any]]:
    """AI が入れた値（標準の値だけ）。並びはフォームの欄の順。"""
    return [
        {
            "field_id": fid,
            "label": field_label(form, fid),
            "value": field_value(form, fid),
            "source": sources.root[fid],
        }
        for fid in field_ids(form)
        if sources.root.get(fid) in AI_SOURCES
    ]


def patient_preview(form: RegimenForm) -> list[dict[str, Any]]:
    """患者のスマホに出る質問（採用される文と型。Claude の文は出ない）。"""
    return [
        {
            "key": q.key,
            "label": q.label,
            "text": q.text,
            "answer_type": q.answer_type,
        }
        for q in form.questions
    ]


# ---------------------------------------------------------------------------
# 採用の前の検査
# ---------------------------------------------------------------------------


def _schedule_key(form: RegimenForm) -> tuple[Any, ...]:
    s = build_schedule(form)
    oral = tuple((r.start, r.end) for r in s.oral_ranges)
    return s.infusion_days, s.pump_removal_day, oral


def _schedule_issues(base: RegimenForm, form: RegimenForm) -> list[FieldIssue]:
    """患者のいるレジメンの版 N+1 で、1コースの日数・薬の Day・抜去日を変えたか。"""
    message = "患者のいるレジメンでは日程を変えられない（新しいレジメンとして作る）"
    if base.basic.cycle_days != form.basic.cycle_days:
        return [FieldIssue("basic.cycle_days", "schedule_locked", message)]
    if _schedule_key(base) != _schedule_key(form):
        return [FieldIssue("drugs", "schedule_locked", message)]
    return []


def _current_version(name: str, skills_dir: Path) -> int | None:
    try:
        return load_skill(name, skills_dir).version
    except SkillValidationError:
        return None


def schedule_lock_issues(
    conn: sqlite3.Connection, draft: dict[str, Any], form: RegimenForm, name: str
) -> list[FieldIssue]:
    """患者のいるレジメンの版 N+1 で日程を変えていないか（新規・患者のいない版は空）。

    adopt は書き込みのトランザクションの中でもう一度呼ぶ（確かめた後に患者が入った場合）。
    """
    if draft["base_version"] is None:
        return []
    if not db.regimen_has_patients(conn, draft["regimen"]):
        return []
    base = form_from_skill(conn, name, int(draft["base_version"]))
    if base is None:
        return [FieldIssue("form", "stale", "元の版の form が無い")]
    return _schedule_issues(base, form)


def _existing_issues(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    form: RegimenForm,
    name: str,
    skills_dir: Path,
) -> list[FieldIssue]:
    if _current_version(name, skills_dir) != int(draft["base_version"]):
        return [FieldIssue("form", "stale", "元の版が変わった（下書きを作り直す）")]
    return schedule_lock_issues(conn, draft, form, name)


def adoption_issues(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    form: RegimenForm,
    *,
    skills_dir: Path,
) -> list[FieldIssue]:
    issues = validate_complete_form(form)
    if issues:
        return issues
    name = draft_skill_name(draft, form)
    if name is None:
        return [FieldIssue("basic.code", "required", "入力が要る")]
    if draft["base_version"] is None:
        taken = code_taken(
            conn, form.basic.code or "", skills_dir=skills_dir, draft_id=draft["id"]
        )
        if taken:
            return [
                FieldIssue("basic.code", "code_taken", "同じ識別名のレジメンがある")
            ]
        return []
    return _existing_issues(conn, draft, form, name, skills_dir)


def render_draft(draft: dict[str, Any], form: RegimenForm) -> str:
    """採用で書く SKILL.md（描けなければ RegimenFormError・SkillValidationError）。"""
    return render_regimen_skill(form, target_version(draft))


def _base_text(
    conn: sqlite3.Connection, name: str, version: int, skills_dir: Path
) -> str:
    saved = db.get_skill_version(conn, name, version)
    if saved is not None:
        return str(saved["content"])
    return read_skill_text(name, skills_dir)


def _skill_md(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    form: RegimenForm,
    skills_dir: Path,
) -> dict[str, str] | None:
    try:
        text = render_draft(draft, form)
    except (RegimenFormError, SkillValidationError, ValueError):
        return None
    name = draft_skill_name(draft, form) or ""
    if draft["base_version"] is None:
        return {"kind": "full", "text": text}
    base = _base_text(conn, name, int(draft["base_version"]), skills_dir)
    return {
        "kind": "diff",
        "text": unified(base, text, path=f"{name}/{SKILL_FILE_NAME}"),
    }


def _issue_out(issue: FieldIssue) -> dict[str, str]:
    return {"field_id": issue.field_id, "code": issue.code, "message": issue.message}


def build_preview(
    conn: sqlite3.Connection, draft: dict[str, Any], *, skills_dir: Path
) -> dict[str, Any]:
    form, sources = draft_form(draft), draft_sources(draft)
    issues = adoption_issues(conn, draft, form, skills_dir=skills_dir)
    return {
        "draft_id": draft["id"],
        "skill_name": draft_skill_name(draft, form),
        "base_version": draft["base_version"],
        "version": target_version(draft),
        "ai_values": ai_values(form, sources),
        "skill_md": None if issues else _skill_md(conn, draft, form, skills_dir),
        "patient_preview": patient_preview(form),
        "issues": [_issue_out(i) for i in issues],
        "confirm_token": confirm_token(form, sources, draft["base_version"]),
    }

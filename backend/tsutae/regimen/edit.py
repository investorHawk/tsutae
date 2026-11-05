"""フォームの欄の書き換え（PATCH .../fields の直接編集。T94 の set_fields も使う）。

`apply_patch(form, sources, patch, *, source, allow_code)` は純関数で、新しいフォームと
出どころを返す（引数は変えない）。手順:

1. 行の削除（`drugs.<row_id>` の形）
2. 行の追加（`RowAdd(section, row_id)`。中身は空。row_id は呼び出し側が決める）
3. 欄の変更（欄の id は `field_ids` の形。`prose` は書けない）。文の欄の "" は None に
   直す（補足の指示 `notes` だけは "" のまま）
4. 型の検査（pydantic。型が違えば欄の id と `type`）と `validate_form`（H1・薬の量・
   投与スケジュールの規則など）

出どころ: 変えた欄に `source`（既定 doctor_edit）を付ける。空にした欄（None・""・[]）と
消した行の出どころは外す（確認の画面の「削除」は欄を空にする直接編集）。

拒むもの（`RegimenFormError`。欄の id と理由）: 未知の欄・行・節、重複する行、識別名の
変更（allow_code=False。既存の版の下書き）、体温の質問を無くす変更。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from tsutae.regimen.form import FieldSource, FieldSources, RegimenForm, field_ids
from tsutae.regimen.text_checks import FieldIssue, RegimenFormError
from tsutae.regimen.validate import ROW_ID_PATTERN, validate_form

__all__ = ["ROW_SECTIONS", "FieldChange", "FormPatch", "RowAdd", "apply_patch"]

ROW_SECTIONS = ("drugs", "side_effects", "questions")
_ROW_ID_RE = re.compile(ROW_ID_PATTERN)
_KEEP_EMPTY_STRING = frozenset({"notes"})


@dataclass(frozen=True)
class FieldChange:
    field_id: str
    value: Any


@dataclass(frozen=True)
class RowAdd:
    section: str
    row_id: str


@dataclass(frozen=True)
class FormPatch:
    changes: tuple[FieldChange, ...] = ()
    adds: tuple[RowAdd, ...] = ()
    deletes: tuple[str, ...] = ()


def _issue(field_id: str, code: str, message: str) -> FieldIssue:
    return FieldIssue(field_id, code, message)


def _row_index(data: dict[str, Any], section: str, row_id: str) -> int | None:
    rows = data.get(section)
    if section not in ROW_SECTIONS or not isinstance(rows, list):
        return None
    return next((i for i, r in enumerate(rows) if r["row_id"] == row_id), None)


def _delete_rows(data: dict[str, Any], deletes: tuple[str, ...]) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    for target in deletes:
        section, _, row_id = target.partition(".")
        index = _row_index(data, section, row_id) if row_id else None
        if index is None:
            issues.append(_issue(target, "unknown_row", "その行は無い"))
            continue
        data[section] = [r for i, r in enumerate(data[section]) if i != index]
    return issues


def _add_rows(data: dict[str, Any], adds: tuple[RowAdd, ...]) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    for add in adds:
        if add.section not in ROW_SECTIONS:
            issues.append(
                _issue(
                    f"{add.section}.{add.row_id}", "unknown_section", "行を足せない節"
                )
            )
        elif not isinstance(add.row_id, str) or not _ROW_ID_RE.fullmatch(add.row_id):
            issues.append(_issue(add.section, "row_id", "行の id の書式が違う"))
        elif _row_index(data, add.section, add.row_id) is not None:
            issues.append(
                _issue(
                    f"{add.section}.{add.row_id}", "row_exists", "同じ id の行がある"
                )
            )
        else:
            data[add.section] = [*data[add.section], {"row_id": add.row_id}]
    return issues


def _normalized(field_id: str, value: Any) -> Any:
    if value == "" and field_id not in _KEEP_EMPTY_STRING:
        return None
    return value


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _set_value(data: dict[str, Any], field_id: str, value: Any) -> None:
    parts = field_id.split(".")
    if len(parts) == 1:
        data[parts[0]] = value
    elif len(parts) == 2:
        data[parts[0]] = {**data[parts[0]], parts[1]: value}
    else:
        section, row_id, name = parts
        index = _row_index(data, section, row_id)
        assert index is not None  # field_ids で確かめた後
        rows = list(data[section])
        rows[index] = {**rows[index], name: value}
        data[section] = rows


def _type_issues(data: dict[str, Any], exc: ValidationError) -> Iterator[FieldIssue]:
    """pydantic の誤りの場所（`('drugs', 0, 'days', 0, 'end')`）を欄の id に直す。"""
    seen: set[str] = set()
    for err in exc.errors(include_input=False, include_url=False):
        loc = err["loc"]
        if loc and loc[0] in ROW_SECTIONS and len(loc) >= 3 and isinstance(loc[1], int):
            row_id = data[loc[0]][loc[1]].get("row_id", f"#{loc[1]}")
            field_id = f"{loc[0]}.{row_id}.{loc[2]}"
        else:
            field_id = ".".join(str(p) for p in loc[:2]) or "form"
        if field_id not in seen:
            seen.add(field_id)
            yield _issue(field_id, "type", "値の型が違う")


def _has_temperature(form: RegimenForm) -> bool:
    return any(q.answer_type == "temperature" for q in form.questions)


def _check_changes(
    form_ids: set[str], patch: FormPatch, allow_code: bool
) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    for change in patch.changes:
        if change.field_id not in form_ids:
            issues.append(_issue(change.field_id, "unknown_field", "その欄は無い"))
        elif change.field_id == "basic.code" and not allow_code:
            issues.append(
                _issue(
                    "basic.code", "code_locked", "既存のレジメンの識別名は変えられない"
                )
            )
    return issues


def _apply_sources(
    sources: FieldSources, patch: FormPatch, new: RegimenForm, source: FieldSource
) -> FieldSources:
    updated = dict(sources.root)
    for change in patch.changes:
        if _is_empty(_normalized(change.field_id, change.value)):
            updated.pop(change.field_id, None)
        else:
            updated[change.field_id] = source
    known = set(field_ids(new))
    return FieldSources({k: v for k, v in updated.items() if k in known})


def apply_patch(
    form: RegimenForm,
    sources: FieldSources,
    patch: FormPatch,
    *,
    source: FieldSource = "doctor_edit",
    allow_code: bool = False,
) -> tuple[RegimenForm, FieldSources]:
    """patch を当てた新しいフォームと出どころ。検査に掛かれば RegimenFormError。"""
    data = form.model_dump()
    issues = [*_delete_rows(data, patch.deletes), *_add_rows(data, patch.adds)]
    if issues:
        raise RegimenFormError(issues)
    staged = RegimenForm.model_validate(data)
    issues = _check_changes(set(field_ids(staged)), patch, allow_code)
    if issues:
        raise RegimenFormError(issues)
    for change in patch.changes:
        _set_value(data, change.field_id, _normalized(change.field_id, change.value))
    try:
        new = RegimenForm.model_validate(data)
    except ValidationError as exc:
        raise RegimenFormError(list(_type_issues(data, exc))) from None
    issues = validate_form(new)
    if _has_temperature(form) and not _has_temperature(new):
        issues.append(
            _issue("questions", "temperature_required", "体温の質問は外せない")
        )
    if issues:
        raise RegimenFormError(issues)
    return new, _apply_sources(sources, patch, new, source)

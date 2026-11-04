"""D4 レジメンのツールの共通の部品（結果の形・入力の検査・欄の当て方。T94）。

- `ok` / `error`: ツールの結果（拒否は is_error で「ref: 理由（コード）」の並び）
- `parse_args`: pydantic で入力を検査（失敗は場所と schema のコード）
- `Plan` / `apply_plan`: 行の ref の対応と FormPatch を `edit.apply_patch` に当てる。
  出どころは doctor_text で当て、`standard` の欄だけを後で付け替える
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from tsutae.regimen.chat_handles import RowHandles
from tsutae.regimen.chat_session import ChatSession, Reason
from tsutae.regimen.edit import FormPatch, apply_patch
from tsutae.regimen.form import FieldSource, FieldSources, RegimenForm
from tsutae.regimen.text_checks import RegimenFormError
from tsutae.regimen.validate import missing_fields

__all__ = [
    "MAX_REASONS",
    "Plan",
    "apply_plan",
    "error",
    "missing_text",
    "ok",
    "parse_args",
    "rejected",
]

MAX_REASONS = 20


# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------


def ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def error(reasons: list[Reason], headline: str) -> dict[str, Any]:
    shown = [f"{ref}: {msg}（{code}）" for ref, code, msg in reasons[:MAX_REASONS]]
    if len(reasons) > MAX_REASONS:
        shown.append(f"ほか {len(reasons) - MAX_REASONS} 件")
    text = f"{headline}（何も受け付けていない）。直してもう一度渡す: " + "; ".join(
        shown
    )
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def parse_args(model: type[BaseModel], args: object) -> tuple[Any, list[Reason]]:
    if not isinstance(args, dict):
        return None, [("(root)", "type", "オブジェクトで渡す")]
    try:
        return model.model_validate(args), []
    except ValidationError as exc:
        reasons = [
            (".".join(str(p) for p in err["loc"]) or "(root)", "schema", err["msg"])
            for err in exc.errors(include_input=False, include_url=False)
        ]
        return None, reasons


def rejected(
    session: ChatSession, tool_name: str, reasons: list[Reason], headline: str
) -> dict[str, Any]:
    session.reject(tool_name, reasons)
    return error(reasons, headline)


def missing_text(session: ChatSession) -> str:
    refs = dict.fromkeys(
        session.handles.ref(i.field_id) for i in missing_fields(session.form)
    )
    return "、".join(refs) or "なし"


def _with_sources(
    sources: FieldSources, overrides: Mapping[str, FieldSource]
) -> FieldSources:
    """apply_patch が付けた出どころのうち、overrides の欄だけを付け替えた新しいもの。"""
    return FieldSources(
        {
            fid: overrides.get(fid, src) if src != "doctor_edit" else src
            for fid, src in sources.root.items()
        }
    )


@dataclass(frozen=True)
class Plan:
    patch: FormPatch
    handles: RowHandles
    standard: tuple[str, ...]  # 出どころを standard にする欄の id
    reasons: tuple[Reason, ...] = ()


def apply_plan(
    session: ChatSession, plan: Plan
) -> tuple[RegimenForm, FieldSources] | list[Reason]:
    try:
        form, sources = apply_patch(
            session.form,
            session.sources,
            plan.patch,
            source="doctor_text",
            allow_code=session.allow_code,
        )
    except RegimenFormError as exc:
        return session.issue_reasons(exc.issues, plan.handles)
    overrides = {fid: "standard" for fid in plan.standard if fid in sources.root}
    return form, _with_sources(sources, overrides)  # type: ignore[arg-type]

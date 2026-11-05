"""D4 レジメンの Claude のツールの本体と SDK MCP サーバー（T94。architecture 9c）。

- `handle_set_fields`: ref を欄の id に直し、`edit.apply_patch`（出どころは doctor_text。
  standard の欄は後で付け替える）で当てる。H1・薬の量・投与スケジュールの規則は
  `validate_form` が見る。先生が直接入れた欄（doctor_edit）への書き込み・その欄のある行の
  削除は `overwrite_requested=true` のときだけ。新規の下書きの識別名は既存の Skill・
  別の開いた下書きと同じなら `code_taken`
- `handle_ask`: 欄の ref（か節の名前）・問い・選択肢 2〜4。文に H1・薬の量などの検査を
  掛け、次の往復の依頼文に入る形（`chat_prompt.ask_line`）にも H1 を掛ける。1往復に1問だけ
- `handle_propose_questions`: chat_propose（部品集の key か新しい3択の質問を足す）

拒否は `is_error` で「ref: 理由（コード）」の並びを返し、Claude に直させる（入力の文面は
返さない。ref は Claude が書いた ref をそのまま返すことがある）。ログ（`regimen_tool`）は
ツール名と accept / reject:<コード> だけ。
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from tsutae.masking import detect_identifiers
from tsutae.regimen.chat_args import (
    ASK,
    ASK_TOOL,
    MAX_ASK_OPTION,
    MAX_ASK_QUESTION,
    PROPOSE_QUESTIONS,
    SERVER_NAME,
    SET_FIELDS,
    SET_FIELDS_TOOL,
    TOOL_DESCRIPTIONS,
    AskArgs,
    SetFieldsArgs,
    tool_schema,
)
from tsutae.regimen.chat_handles import SECTIONS, RowHandles, new_row_id
from tsutae.regimen.chat_prompt import ask_line
from tsutae.regimen.chat_propose import handle_propose_questions
from tsutae.regimen.chat_results import (
    Plan,
    apply_plan,
    missing_text,
    ok,
    parse_args,
    rejected,
)
from tsutae.regimen.chat_session import ChatSession, Reason
from tsutae.regimen.chat_types import AskOut
from tsutae.regimen.edit import FieldChange, FormPatch, RowAdd
from tsutae.regimen.text_checks import text_issues

_PROTECTED = (
    "先生が直接入れた欄。先生が変えるよう頼んだときだけ overwrite_requested=true"
)

__all__ = [
    "build_server",
    "build_tools",
    "handle_ask",
    "handle_propose_questions",
    "handle_set_fields",
]

# ---------------------------------------------------------------------------
# set_fields
# ---------------------------------------------------------------------------


def _plan_rows(
    args: SetFieldsArgs, session: ChatSession
) -> tuple[RowHandles, list[str], list[RowAdd], list[Reason]]:
    handles, deletes, adds, reasons = session.handles, [], [], []
    for ref in args.delete_rows:
        row_id = handles.row_id(ref)
        if row_id is None:
            reasons.append((ref, "unknown_row", "その行は無い"))
            continue
        section = ref.partition(".")[0]
        if session.row_protected(section, row_id) and not args.overwrite_requested:
            reasons.append((ref, "doctor_edit", _PROTECTED))
        deletes.append(f"{section}.{row_id}")
        handles = handles.unbind(ref)
    new_ids: set[str] = set()
    for ref in args.add_rows:
        if not handles.is_free(ref):
            reasons.append(
                (
                    ref,
                    "ref_taken",
                    "使えない ref（今の番号と重ならない新しい番号にする）",
                )
            )
            continue
        section = ref.partition(".")[0]
        row_id = new_row_id(section, session.form, taken=frozenset(new_ids))
        new_ids.add(row_id)
        handles = handles.bind(ref, row_id)
        adds.append(RowAdd(section, row_id))
    return handles, deletes, adds, reasons


def _change_reason(
    ref: str,
    field_id: str | None,
    value: Any,
    args: SetFieldsArgs,
    session: ChatSession,
) -> Reason | None:
    if field_id is None:
        return (ref, "unknown_field", "その欄は無い（ref.欄の名前 で指す）")
    if session.is_protected(field_id) and not args.overwrite_requested:
        return (ref, "doctor_edit", _PROTECTED)
    if (
        field_id == "basic.code"
        and session.allow_code
        and isinstance(value, str)
        and value
        and session.code_taken(value)
    ):
        return (ref, "code_taken", "同じ識別名のレジメンか下書きがある")
    return None


def _plan_set_fields(args: SetFieldsArgs, session: ChatSession) -> Plan:
    handles, deletes, adds, reasons = _plan_rows(args, session)
    changes: list[FieldChange] = []
    standard: list[str] = []
    for item in args.changes:
        field_id = handles.field_id(item.field)
        reason = _change_reason(item.field, field_id, item.value, args, session)
        if reason is not None:
            reasons.append(reason)
            continue
        assert field_id is not None
        changes.append(FieldChange(field_id, item.value))
        if item.source == "standard":
            standard.append(field_id)
    patch = FormPatch(changes=tuple(changes), adds=tuple(adds), deletes=tuple(deletes))
    return Plan(patch, handles, tuple(standard), tuple(reasons))


def handle_set_fields(args: object, session: ChatSession) -> dict[str, Any]:
    """set_fields の本体。検査に通れば session のフォームを変える。"""
    session.called()
    parsed, reasons = parse_args(SetFieldsArgs, args)
    if parsed is None:
        return rejected(session, SET_FIELDS_TOOL, reasons, "set_fields の入力が違う")
    plan = _plan_set_fields(parsed, session)
    if plan.reasons:
        return rejected(
            session, SET_FIELDS_TOOL, list(plan.reasons), "set_fields を受け付けない"
        )
    applied = apply_plan(session, plan)
    if isinstance(applied, list):
        return rejected(session, SET_FIELDS_TOOL, applied, "set_fields の値が違う")
    changed = [c.field_id for c in plan.patch.changes]
    session.commit(*applied, plan.handles, changed)
    session.log(SET_FIELDS_TOOL, "accept")
    refs = "、".join(dict.fromkeys(plan.handles.ref(f) for f in changed)) or "なし"
    return ok(
        f"受け付けた。変えた欄: {refs}。行の削除 {len(plan.patch.deletes)} 件。"
        f"まだ入っていない必須の欄: {missing_text(session)}"
    )


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


def _ask_target(ref: str, session: ChatSession) -> str | None:
    if ref in SECTIONS:
        return ref
    return session.handles.field_id(ref)


def _ask_text_reasons(args: AskArgs) -> list[Reason]:
    reasons: list[Reason] = [
        (i.field_id, i.code, i.message)
        for i in text_issues("question", args.question, max_len=MAX_ASK_QUESTION)
    ]
    for n, option in enumerate(args.options):
        where = f"options.{n}"
        if not option.strip():
            reasons.append((where, "empty", "空の選択肢"))
            continue
        reasons += [
            (i.field_id, i.code, i.message)
            for i in text_issues(where, option, max_len=MAX_ASK_OPTION)
        ]
    if len(set(args.options)) != len(args.options):
        reasons.append(("options", "duplicate", "同じ選択肢が2つある"))
    if not reasons and detect_identifiers(ask_line(args.question, args.options)):
        reasons.append(
            (
                "options",
                "identifier",
                "問いと選択肢をつなぐと個人を特定しうる表現の疑いがある。"
                "数字だけの選択肢は「14日」のように単位を付ける",
            )
        )
    return reasons


def handle_ask(args: object, session: ChatSession) -> dict[str, Any]:
    """ask の本体。1往復に1問だけ受け付け、session.ask に置く。"""
    session.called()
    parsed, reasons = parse_args(AskArgs, args)
    if parsed is None:
        return rejected(session, ASK_TOOL, reasons, "ask の入力が違う")
    if session.ask is not None:
        reasons = [("ask", "one_ask", "1往復に聞けるのは1問だけ。返答の文で終える")]
        return rejected(session, ASK_TOOL, reasons, "ask を受け付けない")
    target = _ask_target(parsed.field, session)
    if target is None:
        reasons.append((parsed.field, "unknown_field", "その欄は無い"))
    reasons += _ask_text_reasons(parsed)
    if reasons:
        return rejected(session, ASK_TOOL, reasons, "ask を受け付けない")
    assert target is not None
    session.ask = AskOut(target, parsed.question, tuple(parsed.options))
    session.log(ASK_TOOL, "accept")
    return ok(
        "受け付けた。画面がこの欄に印を付けて先生に聞く。set_fields を続けず、"
        "返答の文で聞いていることを伝えて終える"
    )


# ---------------------------------------------------------------------------
# SDK
# ---------------------------------------------------------------------------


def build_tools(session: ChatSession) -> list[SdkMcpTool[Any]]:
    """session を閉じ込めた3つのツール（SDK の @tool）。"""

    @tool(SET_FIELDS, TOOL_DESCRIPTIONS[SET_FIELDS], tool_schema(SET_FIELDS))
    async def set_fields(args: dict[str, Any]) -> dict[str, Any]:
        return handle_set_fields(args, session)

    @tool(ASK, TOOL_DESCRIPTIONS[ASK], tool_schema(ASK))
    async def ask(args: dict[str, Any]) -> dict[str, Any]:
        return handle_ask(args, session)

    @tool(
        PROPOSE_QUESTIONS,
        TOOL_DESCRIPTIONS[PROPOSE_QUESTIONS],
        tool_schema(PROPOSE_QUESTIONS),
    )
    async def propose_questions(args: dict[str, Any]) -> dict[str, Any]:
        return handle_propose_questions(args, session)

    return [set_fields, ask, propose_questions]


def build_server(session: ChatSession) -> McpSdkServerConfig:
    """名前 `tsutae_regimen` の SDK MCP サーバー（ツール set_fields・ask・propose_questions）。"""
    return create_sdk_mcp_server(SERVER_NAME, tools=build_tools(session))

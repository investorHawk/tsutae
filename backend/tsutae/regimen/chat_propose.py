"""D4 レジメンのツール propose_questions の本体（T94。architecture 9c）。

部品集の key か新しい3択の質問（key・短い名前・文）を questions の行に足す。足した行の
row_id はサーバーが振る（`question1` など）。拒否するもの: 部品集に無い key・フォームに
もうある key・部品集にある key を新しい質問として足す・予約語（temperature）。文の検査
（H1・薬の量・長さ・YAML の読み戻し）と体温の質問の数は `edit.apply_patch` が見る。

Claude が自分で提案する質問（source=standard）は、基本・投与スケジュール・注意する症状の
必須の欄（`missing_fields` の basic・drugs・side_effects）がそろうまで `not_ready` で拒否する
（spec 9.1「そろってから、副作用をもとに提案する」）。先生が文で質問を指定したとき
（source=doctor_text）はそろう前でも足せる。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tsutae.db.repo_question_library import RESERVED_KEYS
from tsutae.regimen.chat_args import PROPOSE_QUESTIONS_TOOL, ProposeQuestionsArgs
from tsutae.regimen.chat_handles import new_row_id
from tsutae.regimen.chat_results import (
    Plan,
    apply_plan,
    ok,
    parse_args,
    rejected,
)
from tsutae.regimen.chat_session import ChatSession, Reason
from tsutae.regimen.edit import FieldChange, FormPatch, RowAdd
from tsutae.regimen.form import RegimenForm
from tsutae.regimen.validate import missing_fields

__all__ = ["handle_propose_questions", "ready_for_proposals"]

_READY_SECTIONS = ("basic", "drugs", "side_effects")
_NOT_READY = (
    "基本・投与スケジュール・注意する症状を先に埋める（先生が文で質問を指定したときだけ "
    "source=doctor_text で足せる）"
)


def ready_for_proposals(form: RegimenForm) -> bool:
    """基本・薬・注意する症状の必須の欄がそろっているか。"""
    return not any(
        issue.field_id.partition(".")[0] in _READY_SECTIONS
        for issue in missing_fields(form)
    )


def _question_items(
    args: ProposeQuestionsArgs, session: ChatSession
) -> tuple[list[dict[str, str]], list[Reason]]:
    existing = {q.key for q in session.form.questions if q.key is not None}
    items: list[dict[str, str]] = []
    reasons: list[Reason] = []
    for n, key in enumerate(args.from_library):
        item = session.library.get(key)
        if item is None:
            reasons.append(
                (f"from_library.{n}", "unknown_library_key", "部品集に無い key")
            )
        elif key in existing:
            reasons.append(
                (f"from_library.{n}", "key_exists", "この key の質問はもうある")
            )
        else:
            existing.add(key)
            items.append(
                {
                    "key": key,
                    "label": item.label,
                    "text": item.text,
                    "answer_type": item.answer_type,
                }
            )
    for n, q in enumerate(args.new_questions):
        where = f"new_questions.{n}.key"
        if q.key in session.library:
            reasons.append(
                (where, "library_key", "部品集にある key。from_library で選ぶ")
            )
        elif q.key in RESERVED_KEYS:
            reasons.append((where, "reserved", "この key は使えない"))
        elif q.key in existing:
            reasons.append((where, "key_exists", "この key の質問はもうある"))
        else:
            existing.add(q.key)
            items.append(
                {
                    "key": q.key,
                    "label": q.label,
                    "text": q.text,
                    "answer_type": "three_level",
                }
            )
    if not items and not reasons:
        reasons.append(("(root)", "empty", "足す質問が無い"))
    return items, reasons


def _plan_questions(
    items: Iterable[dict[str, str]], session: ChatSession, source: str
) -> Plan | list[Reason]:
    handles, adds, changes, new_ids = session.handles, [], [], set()
    for item in items:
        ref = handles.next_free("questions")
        if ref is None:
            return [("questions", "too_many", "これ以上は足せない")]
        row_id = new_row_id("questions", session.form, taken=frozenset(new_ids))
        new_ids.add(row_id)
        handles = handles.bind(ref, row_id)
        adds.append(RowAdd("questions", row_id))
        changes += [
            FieldChange(f"questions.{row_id}.{name}", value)
            for name, value in item.items()
        ]
    standard = tuple(c.field_id for c in changes) if source == "standard" else ()
    patch = FormPatch(changes=tuple(changes), adds=tuple(adds))
    return Plan(patch, handles, standard)


def handle_propose_questions(args: object, session: ChatSession) -> dict[str, Any]:
    """propose_questions の本体。検査に通れば questions の行を足す。"""
    session.called()
    parsed, reasons = parse_args(ProposeQuestionsArgs, args)
    if parsed is None:
        return rejected(
            session, PROPOSE_QUESTIONS_TOOL, reasons, "propose_questions の入力が違う"
        )
    if parsed.source == "standard" and not ready_for_proposals(session.form):
        reasons = [("(root)", "not_ready", _NOT_READY)]
        return rejected(
            session, PROPOSE_QUESTIONS_TOOL, reasons, "propose_questions を受け付けない"
        )
    items, reasons = _question_items(parsed, session)
    plan = _plan_questions(items, session, parsed.source) if not reasons else None
    if isinstance(plan, list):
        reasons = plan
    applied = apply_plan(session, plan) if isinstance(plan, Plan) else reasons
    if isinstance(applied, list):
        return rejected(
            session, PROPOSE_QUESTIONS_TOOL, applied, "propose_questions を受け付けない"
        )
    assert isinstance(plan, Plan)
    session.commit(*applied, plan.handles, [c.field_id for c in plan.patch.changes])
    session.proposed += [item["key"] for item in items]
    session.log(PROPOSE_QUESTIONS_TOOL, "accept")
    refs = [plan.handles.ref(f"questions.{a.row_id}") for a in plan.patch.adds]
    return ok(
        f"受け付けた。足した質問: {'、'.join(refs)}。症状の行の question_key に"
        "つなぐときは set_fields で入れる"
    )

"""propose_questions は基本・投与スケジュール・注意する症状がそろってから（spec 9.1）。

Claude が自分で提案する質問（source=standard）は、基本（画面の名前・識別名・1コースの
日数）・薬・注意する症状の必須の欄がそろうまで `not_ready` で拒否する。先生が文で質問を
指定したとき（source=doctor_text）は、そろう前でも足せる。
"""

from __future__ import annotations

from typing import Any

import pytest
from regimen_chat_fakes import ready_form

from tsutae.db.repo_question_library import SEED_QUESTIONS
from tsutae.regimen.chat_prompt import build_turn_prompt
from tsutae.regimen.chat_session import ChatSession
from tsutae.regimen.chat_tools import handle_propose_questions, handle_set_fields
from tsutae.regimen.chat_types import LibraryItem, TurnInput
from tsutae.regimen.form import FieldSources, RegimenForm
from tsutae.regimen.source import new_draft_form

LIBRARY = tuple(LibraryItem(**dict(item)) for item in SEED_QUESTIONS)


def _session(form: RegimenForm) -> ChatSession:
    draft = TurnInput(draft_id=1, form=form, sources=FieldSources({}), library=LIBRARY)
    return ChatSession(draft)


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def test_standard_proposal_on_an_empty_draft_is_not_ready() -> None:
    session = _session(new_draft_form())
    result = handle_propose_questions({"from_library": ["diarrhea"]}, session)
    assert result["is_error"] is True
    assert "not_ready" in _text(result)
    assert [q.key for q in session.form.questions] == ["fever"]
    assert session.rejected == 1


@pytest.mark.parametrize(
    "missing",
    ["basic", "drugs", "side_effects"],
)
def test_each_section_must_be_filled(missing: str) -> None:
    form = ready_form()
    if missing == "basic":
        form = form.model_copy(
            update={"basic": form.basic.model_copy(update={"cycle_days": None})}
        )
    else:
        form = form.model_copy(update={missing: []})
    result = handle_propose_questions({"from_library": ["diarrhea"]}, _session(form))
    assert result["is_error"] is True and "not_ready" in _text(result)


def test_standard_proposal_on_a_ready_draft_is_accepted() -> None:
    session = _session(ready_form())
    result = handle_propose_questions({"from_library": ["diarrhea"]}, session)
    assert not result.get("is_error"), _text(result)
    assert [q.key for q in session.form.questions] == ["fever", "diarrhea"]


def test_doctor_specified_question_can_be_added_early() -> None:
    session = _session(new_draft_form())
    result = handle_propose_questions(
        {"from_library": ["diarrhea"], "source": "doctor_text"}, session
    )
    assert not result.get("is_error"), _text(result)
    assert session.sources.root["questions.question1.key"] == "doctor_text"


def test_fields_set_in_the_same_turn_count() -> None:
    """同じ往復の set_fields で埋めた後なら提案できる。"""
    form = ready_form()
    session = _session(
        form.model_copy(
            update={"basic": form.basic.model_copy(update={"cycle_days": None})}
        )
    )
    handle_set_fields(
        {
            "changes": [
                {"field": "basic.cycle_days", "value": 14, "source": "doctor_text"}
            ]
        },
        session,
    )
    result = handle_propose_questions({"from_library": ["diarrhea"]}, session)
    assert not result.get("is_error"), _text(result)


def test_prompt_has_the_rule() -> None:
    draft = TurnInput(
        draft_id=1, form=new_draft_form(), sources=FieldSources({}), library=LIBRARY
    )
    prompt = build_turn_prompt(draft, "x")
    assert "そろってから" in prompt

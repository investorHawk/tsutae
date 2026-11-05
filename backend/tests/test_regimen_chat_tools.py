"""tsutae.regimen.chat_tools: Claude のツール set_fields・ask・propose_questions の本体。

ツールは DB に書かない。ChatSession の中のフォーム・出どころに当て、検査（pydantic・
validate_form・apply_patch）に通らなければ理由（欄の ref とコード）を is_error で返す。
"""

from __future__ import annotations

from typing import Any

import pytest
from regimen_chat_fakes import ready_form

from tsutae.db.repo_question_library import SEED_QUESTIONS
from tsutae.pipeline.logs import MemoryLogger
from tsutae.regimen.chat_session import ChatSession
from tsutae.regimen.chat_tools import (
    handle_ask,
    handle_propose_questions,
    handle_set_fields,
)
from tsutae.regimen.chat_types import LibraryItem, TurnInput
from tsutae.regimen.form import FieldSources, RegimenForm, load_builtin_form
from tsutae.regimen.source import new_draft_form
from tsutae.schemas import RunStats

LIBRARY = tuple(LibraryItem(**dict(item)) for item in SEED_QUESTIONS)


def _session(
    form: RegimenForm | None = None,
    sources: dict[str, str] | None = None,
    *,
    allow_code: bool = True,
    taken: frozenset[str] = frozenset(),
    logger: MemoryLogger | None = None,
) -> ChatSession:
    draft = TurnInput(
        draft_id=1,
        form=form if form is not None else new_draft_form(),
        sources=FieldSources(sources or {}),
        library=LIBRARY,
        allow_code=allow_code,
        code_taken=lambda code: code in taken,
    )
    return ChatSession(draft, logger or MemoryLogger())


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def _ok(result: dict[str, Any]) -> bool:
    return not result.get("is_error", False)


def _change(field: str, value: Any, source: str = "doctor_text") -> dict[str, Any]:
    return {"field": field, "value": value, "source": source}


# ---------------------------------------------------------------------------
# set_fields
# ---------------------------------------------------------------------------


def test_set_fields_fills_fields_with_sources() -> None:
    logger = MemoryLogger()
    session = _session(logger=logger)
    result = handle_set_fields(
        {
            "changes": [
                _change("basic.display_name", "FOLFIRI＋BV"),
                _change("basic.code", "FOLFIRI-BV"),
                _change("basic.cycle_days", 14),
                _change("basic.target", "大腸がん", "standard"),
                _change("drugs.1.name", "ベバシズマブ"),
                _change("drugs.1.route", "infusion"),
                _change("drugs.1.days", [{"start": 1, "end": 1}]),
            ],
            "add_rows": ["drugs.1"],
        },
        session,
    )
    assert _ok(result), _text(result)
    form = session.form
    assert form.basic.cycle_days == 14
    assert form.drugs[0].row_id == "drug1"
    assert form.drugs[0].name == "ベバシズマブ"
    assert session.sources.root["basic.target"] == "standard"
    assert session.sources.root["drugs.drug1.name"] == "doctor_text"
    assert "basic.cycle_days" in session.changed
    assert "drugs.drug1.days" in session.changed
    # 結果の文は ref で欄を示す（row_id を出さない）
    assert "drugs.1.days" in _text(result)
    assert [r["decision"] for r in logger.find("regimen_tool")] == ["accept"]
    assert logger.find("regimen_tool")[0]["tool_name"] == (
        "mcp__tsutae_regimen__set_fields"
    )


def test_set_fields_rejects_dose_and_keeps_form() -> None:
    logger = MemoryLogger()
    session = _session(load_builtin_form("regimen-folfox"), logger=logger)
    before = session.form
    result = handle_set_fields(
        {"changes": [_change("drugs.1.name", "オキサリプラチン 85mg/m2")]}, session
    )
    assert not _ok(result)
    assert "drugs.1.name" in _text(result) and "dose" in _text(result)
    assert session.form == before
    assert session.rejected == 1
    assert logger.find("regimen_tool")[0]["decision"] == "reject:dose"


def test_set_fields_rejects_identifier_in_value() -> None:
    session = _session(load_builtin_form("regimen-folfox"))
    result = handle_set_fields(
        {"changes": [_change("notes", "受付 A-023 の患者は別")]}, session
    )
    assert not _ok(result)
    assert "identifier" in _text(result)
    assert "A-023" not in _text(result)
    assert session.form.notes == ""


def test_set_fields_protects_doctor_edit() -> None:
    form = load_builtin_form("regimen-folfox")
    sources = {"drugs.d-fu-pump.days": "doctor_edit"}
    session = _session(form, sources)
    change = _change("drugs.4.days", [{"start": 1, "end": 2}])
    result = handle_set_fields({"changes": [change]}, session)
    assert not _ok(result)
    assert "doctor_edit" in _text(result) and "drugs.4.days" in _text(result)
    assert session.form.drugs[3].days[0].end == 3
    # 行ごと消すのも同じ
    result = handle_set_fields({"delete_rows": ["drugs.4"]}, session)
    assert not _ok(result)
    assert len(session.form.drugs) == 4
    # 先生が頼んだときだけ変えられる
    result = handle_set_fields(
        {"changes": [change], "overwrite_requested": True}, session
    )
    assert _ok(result), _text(result)
    assert session.form.drugs[3].days[0].end == 2
    assert session.sources.root["drugs.d-fu-pump.days"] == "doctor_text"


def test_set_fields_unknown_refs_and_row_ids() -> None:
    session = _session(load_builtin_form("regimen-folfox"))
    result = handle_set_fields(
        {
            "changes": [
                _change("drugs.d-oxaliplatin.name", "x"),
                _change("drugs.9.name", "x"),
                _change("prose", "x"),
            ]
        },
        session,
    )
    assert not _ok(result)
    assert _text(result).count("unknown_field") == 3


def test_set_fields_add_row_needs_free_ref() -> None:
    session = _session(load_builtin_form("regimen-folfox"))
    result = handle_set_fields({"add_rows": ["drugs.2"]}, session)
    assert not _ok(result) and "ref_taken" in _text(result)
    ok = handle_set_fields(
        {
            "add_rows": ["drugs.5"],
            "changes": [_change("drugs.5.name", "ベバシズマブ", "standard")],
        },
        session,
    )
    assert _ok(ok), _text(ok)
    # 消した行の ref は同じ往復で使い回さない
    assert _ok(handle_set_fields({"delete_rows": ["drugs.5"]}, session))
    again = handle_set_fields({"add_rows": ["drugs.5"]}, session)
    assert not _ok(again)


def test_set_fields_code_taken_and_locked() -> None:
    session = _session(taken=frozenset({"FOLFOX"}))
    result = handle_set_fields({"changes": [_change("basic.code", "FOLFOX")]}, session)
    assert not _ok(result) and "code_taken" in _text(result)
    locked = _session(load_builtin_form("regimen-capox"), allow_code=False)
    result = handle_set_fields({"changes": [_change("basic.code", "CAPOX-2")]}, locked)
    assert not _ok(result) and "code_locked" in _text(result)


def test_set_fields_cannot_remove_temperature_question() -> None:
    session = _session()
    result = handle_set_fields({"delete_rows": ["questions.1"]}, session)
    assert not _ok(result)
    assert "temperature_required" in _text(result)


@pytest.mark.parametrize(
    "args",
    [
        "not an object",
        {"changes": [{"field": "notes", "value": "x", "source": "doctor_edit"}]},
        {"changes": [{"field": "notes", "value": "x"}]},
        {"unknown": 1},
        {"overwrite_requested": "yes"},
    ],
)
def test_set_fields_schema_errors(args: Any) -> None:
    session = _session()
    result = handle_set_fields(args, session)
    assert not _ok(result)
    assert session.rejected == 1


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


def test_ask_returns_field_question_and_options() -> None:
    session = _session(load_builtin_form("regimen-folfox"))
    args = {
        "field": "drugs.4.days",
        "question": "ポンプは何日目に外しますか",
        "options": ["Day3", "Day2"],
    }
    result = handle_ask(args, session)
    assert _ok(result), _text(result)
    assert session.ask is not None
    assert session.ask.field_id == "drugs.d-fu-pump.days"
    assert session.ask.options == ("Day3", "Day2")
    # 1往復に1問だけ
    assert not _ok(handle_ask(args, session))
    assert session.ask.question == "ポンプは何日目に外しますか"


def test_ask_can_point_at_a_section() -> None:
    session = _session()
    args = {"field": "drugs", "question": "どの薬を使いますか", "options": ["a", "b"]}
    assert _ok(handle_ask(args, session))
    assert session.ask is not None and session.ask.field_id == "drugs"


@pytest.mark.parametrize(
    "args, code",
    [
        ({"field": "drugs.9.days", "question": "q", "options": ["a", "b"]}, "unknown"),
        ({"field": "notes", "question": "q", "options": ["a"]}, ""),
        ({"field": "notes", "question": "q", "options": ["a"] * 5}, ""),
        ({"field": "notes", "question": "q", "options": ["a", "a"]}, "duplicate"),
        (
            {"field": "notes", "question": "田中様の件は？", "options": ["a", "b"]},
            "identifier",
        ),
        (
            {"field": "notes", "question": "量は?", "options": ["85mg/m2", "100mg"]},
            "dose",
        ),
    ],
)
def test_ask_rejects(args: dict[str, Any], code: str) -> None:
    session = _session(load_builtin_form("regimen-folfox"))
    result = handle_ask(args, session)
    assert not _ok(result)
    assert code in _text(result)
    assert session.ask is None
    assert "田中" not in _text(result)


# ---------------------------------------------------------------------------
# propose_questions
# ---------------------------------------------------------------------------


def test_propose_from_library_and_new() -> None:
    session = _session(ready_form())
    result = handle_propose_questions(
        {
            "from_library": ["diarrhea"],
            "new_questions": [
                {
                    "key": "fatigue",
                    "label": "だるさ",
                    "text": "だるさや疲れやすさはありましたか",
                }
            ],
        },
        session,
    )
    assert _ok(result), _text(result)
    keys = [q.key for q in session.form.questions]
    assert keys == ["fever", "diarrhea", "fatigue"]
    added = session.form.questions[1]
    assert added.row_id == "question1"
    assert added.text == "下痢はありましたか" and added.answer_type == "three_level"
    assert session.form.questions[2].answer_type == "three_level"
    assert session.sources.root["questions.question2.text"] == "standard"
    assert session.proposed == ["diarrhea", "fatigue"]
    assert "questions.2" in _text(result) and "questions.3" in _text(result)


@pytest.mark.parametrize(
    "args, code",
    [
        ({"from_library": ["nothing"]}, "unknown_library_key"),
        ({"from_library": ["fever"]}, "key_exists"),
        (
            {"new_questions": [{"key": "diarrhea", "label": "x", "text": "y"}]},
            "library_key",
        ),
        (
            {"new_questions": [{"key": "temperature", "label": "x", "text": "y"}]},
            "reserved",
        ),
        (
            {"new_questions": [{"key": "pain", "label": "痛み", "text": "痛みは 5mg"}]},
            "dose",
        ),
        (
            {"new_questions": [{"key": "p_ab123", "label": "痛み", "text": "痛み"}]},
            "identifier",
        ),
        ({}, "empty"),
    ],
)
def test_propose_rejects(args: dict[str, Any], code: str) -> None:
    session = _session(ready_form())
    result = handle_propose_questions(args, session)
    assert not _ok(result)
    assert code in _text(result)
    assert [q.key for q in session.form.questions] == ["fever"]


def test_session_result_counts_calls() -> None:
    session = _session()
    handle_set_fields({"changes": [_change("basic.cycle_days", 99)]}, session)
    handle_set_fields({"changes": [_change("basic.cycle_days", 21)]}, session)
    result = session.result("1コースを21日にした", RunStats(cost_usd=0.1))
    assert result.tool_calls == 2 and result.rejected == 1
    assert result.changed == ("basic.cycle_days",)
    assert result.form.basic.cycle_days == 21
    assert result.reply == "1コースを21日にした"
    assert result.stats.cost_usd == 0.1

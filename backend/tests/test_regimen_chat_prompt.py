"""tsutae.regimen.chat_prompt: 1往復の依頼文（今のフォーム・出どころ・会話・部品集・用語・規則）。

依頼文は H1（detect_identifiers）を通る形でなければならない（row_id を出さない）。
"""

from __future__ import annotations

import pytest
from regimen_fixtures import EXTRA_REGIMENS, extra_form

from tsutae.db.repo_question_library import SEED_QUESTIONS
from tsutae.masking import detect_identifiers
from tsutae.regimen.chat_prompt import (
    HISTORY_ROWS,
    SYSTEM_PROMPT,
    build_turn_prompt,
)
from tsutae.regimen.chat_rows import REPLY_HIDDEN
from tsutae.regimen.chat_types import LibraryItem, TurnInput
from tsutae.regimen.form import FieldSources, RegimenForm, load_builtin_form
from tsutae.regimen.source import new_draft_form
from tsutae.synthetic import load_terms

LIBRARY = tuple(LibraryItem(**dict(item)) for item in SEED_QUESTIONS)
TEXT = "FOLFIRI＋BV を作りたい。14日ごと、ベバシズマブは Day1"


def _input(form: RegimenForm, **kw: object) -> TurnInput:
    return TurnInput(
        draft_id=1,
        form=form,
        sources=kw.pop("sources", FieldSources({})),  # type: ignore[arg-type]
        library=LIBRARY,
        **kw,  # type: ignore[arg-type]
    )


def _forms() -> list[RegimenForm]:
    return [
        new_draft_form(),
        load_builtin_form("regimen-folfox"),
        load_builtin_form("regimen-capox"),
        *(extra_form(name) for name in EXTRA_REGIMENS),
    ]


@pytest.mark.parametrize("index", range(6))
def test_prompt_passes_h1(index: int) -> None:
    form = _forms()[index]
    prompt = build_turn_prompt(_input(form), TEXT)
    assert detect_identifiers(prompt) == []
    for row in [*form.drugs, *form.side_effects, *form.questions]:
        assert f'"{row.row_id}"' not in prompt


def test_system_prompt_passes_h1() -> None:
    assert detect_identifiers(SYSTEM_PROMPT) == []
    # 伏せた返答の固定文も次の往復の依頼文（直近の会話）に入る
    assert detect_identifiers(REPLY_HIDDEN) == []


def test_prompt_contains_form_library_terms_and_text() -> None:
    form = load_builtin_form("regimen-folfox")
    prompt = build_turn_prompt(_input(form), TEXT)
    assert f"<<<\n{TEXT}\n>>>" in prompt
    assert '"ref": "drugs.4"' in prompt
    assert "フルオロウラシル（46時間）" in prompt
    for term in load_terms():
        assert term["term"] in prompt
    for item in LIBRARY:
        assert item.key in prompt and item.text in prompt
    # 描画用の文（prose）は入れない
    assert "pump_sentence" not in prompt


@pytest.mark.parametrize(
    "phrase",
    [
        "source=standard",
        "source=doctor_text",
        "ask",
        "選択肢",
        "薬の量",
        "overwrite_requested",
        "体温の質問は外せない",
        "3択",
        "propose_questions",
        "set_fields",
    ],
)
def test_prompt_has_rules(phrase: str) -> None:
    prompt = build_turn_prompt(_input(new_draft_form()), TEXT)
    assert phrase in prompt


def test_prompt_keeps_unlisted_symptoms_out_of_near_terms() -> None:
    prompt = build_turn_prompt(_input(new_draft_form()), TEXT)
    assert "用語の一覧に無い症状は ctcae_terms に入れず、notes に書く" in prompt
    assert "一覧に無い症状の言い方を、近い用語の行の phrases に混ぜない" in prompt
    assert "「歯ぐきから血が出る」を「鼻出血」の行に入れない" in prompt
    # 例の前提: 歯肉出血は一覧に無く、鼻出血はある
    terms = {item["term"] for item in load_terms()}
    assert "歯肉出血" not in terms and "鼻出血" in terms


def test_prompt_fixes_the_bleeding_question() -> None:
    """出血は鼻血と歯ぐきの両方を聞く（先生の判断 2026-11-06）。文と key を固定する。"""
    prompt = build_turn_prompt(_input(new_draft_form()), TEXT)
    assert "文を「鼻血や歯ぐきからの出血はありましたか」" in prompt
    assert "key を bleeding に固定する" in prompt
    assert "鼻血だけの文に縮めない" in prompt


def test_near_terms_rule_is_about_side_effect_rows_not_the_question() -> None:
    """規則「phrases に混ぜない」は残す。質問の文を縮める理由にはしない。"""
    prompt = build_turn_prompt(_input(new_draft_form()), TEXT)
    assert (
        "これは side_effects の行の話で、患者への質問の文を鼻血だけに縮める理由にはならない"
        in prompt
    )
    assert "歯ぐきの言い方は side_effects の phrases に入れない" in prompt


def test_prompt_lists_doctor_edit_and_missing_fields_by_ref() -> None:
    form = load_builtin_form("regimen-folfox")
    sources = FieldSources(
        {"drugs.d-fu-pump.days": "doctor_edit", "basic.target": "standard"}
    )
    prompt = build_turn_prompt(_input(form, sources=sources), TEXT)
    assert "drugs.4.days" in prompt
    assert "d-fu-pump" not in prompt
    new_prompt = build_turn_prompt(_input(new_draft_form()), TEXT)
    assert "basic.display_name" in new_prompt  # まだ入っていない必須の欄


def test_history_keeps_recent_rows_without_field_ids() -> None:
    history = [
        {"role": "doctor", "text": f"先生の文{i}", "generation": i, "at": "x"}
        for i in range(HISTORY_ROWS + 3)
    ]
    history.append(
        {
            "role": "assistant",
            "text": "日数を入れた",
            "changed": ["drugs.d-fu-pump.days"],
            "ask": {
                "field_id": "drugs.d-fu-pump.days",
                "question": "ポンプは何日目に外しますか",
                "options": ["Day3", "Day2"],
            },
            "generation": 9,
            "at": "x",
        }
    )
    history.append(
        {
            "role": "system",
            "kind": "turn_failed",
            "reason": "timeout",
            "generation": 10,
            "at": "x",
        }
    )
    form = load_builtin_form("regimen-folfox")
    prompt = build_turn_prompt(_input(form, history=tuple(history)), TEXT)
    assert "先生の文0" not in prompt
    assert f"先生の文{HISTORY_ROWS + 2}" in prompt
    assert "日数を入れた" in prompt
    assert "ポンプは何日目に外しますか" in prompt
    assert "d-fu-pump" not in prompt
    assert "失敗" in prompt
    assert detect_identifiers(prompt) == []


def test_prompt_without_history_says_so() -> None:
    prompt = build_turn_prompt(_input(new_draft_form()), TEXT)
    assert "（まだ無い）" in prompt

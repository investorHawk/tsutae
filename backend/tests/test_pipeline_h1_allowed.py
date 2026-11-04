"""H1 の許す一覧（医師が「個人を特定する語は無いことを確かめた」語。D6）。症例は全て合成。

H1 の値を固定しているテスト（test_pipeline_hooks.py）は変えない。ここでは足した引数
`allowed` だけを確かめる:

- 許す一覧が空なら今と同じ（同じ入力に同じ結果・同じログ）
- 許した語の出現に完全に含まれる検出だけを無視し、`hook_h1_confirmed` を残す
- ほかの検出・はみ出す検出は今までどおり止める
- convert のコードの段（依頼文の二次）も同じ語だけを無視し、SDK の H1 にも渡る
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from pipeline_fakes import FakeRunner, load_case, regimen_skill, report_skill

from tsutae.config import SKILLS_HOME, get_settings
from tsutae.dataset import to_courses, to_entries
from tsutae.masking import RULE_LONG_DIGITS, detect_identifiers
from tsutae.masking.manual import detect_in_prompt
from tsutae.pipeline.hooks import build_hooks, make_h1
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.orchestrator import build_options, convert
from tsutae.pipeline.prompt import build_prompt
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL, RunCollector
from tsutae.schemas import DoctorMask, TextSpan

CTX: dict[str, Any] = {"signal": None}
SETTINGS = replace(get_settings(), skills_dir=SKILLS_HOME / ".claude" / "skills")
SUSPECT = 38  # demo_patient の「磯鷲さんに…」
PROMPTS = ["担当者さんに聞いた", "連絡は x@y まで", "下痢が3回あった", None]


def _prompt(text: str | None) -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": text}


@pytest.mark.parametrize("text", PROMPTS)
async def test_empty_allowed_behaves_exactly_as_before(text: str | None) -> None:
    old_logger, new_logger = MemoryLogger(), MemoryLogger()
    old = await make_h1(old_logger)(_prompt(text), None, CTX)
    new = await make_h1(new_logger, allowed=())(_prompt(text), None, CTX)
    assert new == old
    assert new_logger.records == old_logger.records


@pytest.mark.parametrize("text", PROMPTS[:3])
def test_detect_in_prompt_without_allowed_is_detect_identifiers(text: str) -> None:
    assert detect_in_prompt(text) == detect_identifiers(text)
    assert detect_in_prompt(text, ()) == detect_identifiers(text)


async def test_allowed_word_is_ignored_and_logged() -> None:
    logger = MemoryLogger()
    h1 = make_h1(logger, allowed=("担当者さん",))
    assert await h1(_prompt("担当者さんに聞いた"), None, CTX) == {}
    assert logger.records == [
        {"event": "hook_h1_confirmed", "hook_name": "H1", "decision": "confirmed:1"},
        {"event": "hook_h1_allow", "hook_name": "H1", "decision": "allow"},
    ]


async def test_other_detections_still_block() -> None:
    logger = MemoryLogger()
    h1 = make_h1(logger, allowed=("担当者さん",))
    result = await h1(_prompt("担当者さんと1234567"), None, CTX)
    assert result["decision"] == "block"
    assert result["reason"] == RULE_LONG_DIGITS
    assert logger.find("hook_h1_block")[0]["decision"] == f"block:{RULE_LONG_DIGITS}"


async def test_detection_wider_than_allowed_word_still_blocks() -> None:
    h1 = make_h1(MemoryLogger(), allowed=("1234567",))
    result = await h1(_prompt("番号は12345678"), None, CTX)
    assert result["decision"] == "block"


async def test_allowed_word_is_matched_in_json_form() -> None:
    # 依頼文は JSON（ensure_ascii=False）。改行を含む語は \\n の形で探す
    word = "磯鷲\n南さん"
    prompt = '{"masked_free_text": "磯鷲\\n南さんに聞いた"}'
    assert detect_identifiers(prompt)
    h1 = make_h1(MemoryLogger(), allowed=(word,))
    assert await h1(_prompt(prompt), None, CTX) == {}


async def test_build_hooks_passes_allowed_to_h1() -> None:
    hooks = build_hooks(
        masked_texts={1: "担当者さんに聞いた"},
        logger=MemoryLogger(),
        allowed_tools=("Task", "Agent", "Skill", EMIT_TIMELINE_TOOL, EMIT_REPORT_TOOL),
        allowed_subagents=("date-normalizer",),
        allowed_suspects=("担当者さん",),
    )
    h1 = hooks["UserPromptSubmit"][0].hooks[0]
    assert await h1(_prompt("担当者さんに聞いた"), None, CTX) == {}


# --- convert（コードの段と SDK の H1） ---------------------------------------------


def _confirmed_prepared():
    patient, _labels = load_case("demo_patient")
    return prepare_input(
        courses=to_courses(patient),
        entries=to_entries(patient),
        regimen_skill=regimen_skill(patient.regimen),
        report_skill=report_skill(),
        visit_date=patient.visit_date,
        doctor_masks={
            SUSPECT: DoctorMask(
                confirmed_clear=True, allowed=[TextSpan(start=0, end=4)]
            )
        },
    )


async def test_convert_lets_confirmed_record_reach_the_runner() -> None:
    prepared = _confirmed_prepared()
    assert prepared.allowed_suspects == ["磯鷲さん"]
    runner = FakeRunner()
    logger = MemoryLogger()
    await convert(prepared, runner=runner, logger=logger, settings=SETTINGS)
    assert runner.calls == 1
    assert not runner.blocked
    assert "磯鷲さん" in runner.prompts[0]
    assert logger.find("hook_h1_block") == []
    assert logger.find("hook_h1_confirmed") == [
        {"event": "hook_h1_confirmed", "hook_name": "H1", "decision": "confirmed:1"}
    ]


async def test_convert_without_allowed_still_stops_the_same_text() -> None:
    prepared = _confirmed_prepared().model_copy(update={"allowed_suspects": []})
    runner = FakeRunner()
    logger = MemoryLogger()
    result = await convert(prepared, runner=runner, logger=logger, settings=SETTINGS)
    assert runner.calls == 0
    assert result.error_code == "h1_blocked"


def test_build_options_wires_allowed_into_h1(tmp_path) -> None:
    prepared = _confirmed_prepared()
    options = build_options(
        prepared,
        RunCollector.from_prepared(prepared),
        MemoryLogger(),
        SETTINGS,
        tmp_path,
    )
    assert "磯鷲さん" in build_prompt(prepared)
    assert options.hooks is not None
    assert len(options.hooks["UserPromptSubmit"]) == 1

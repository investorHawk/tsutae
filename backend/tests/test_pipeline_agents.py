"""tsutae.pipeline.agents（3役の AgentDefinition）。"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from claude_agent_sdk import AgentDefinition

from tsutae.config import get_settings
from tsutae.masking import detect_identifiers
from tsutae.pipeline.agents import (
    AGENT_NAMES,
    CONTRADICTION_FINDER,
    DATE_NORMALIZER,
    TERM_MAPPER,
    build_agents,
)
from tsutae.synthetic import load_terms

SETTINGS = replace(get_settings(), subagent_model="claude-test-sub")
HIRAGANA = re.compile("[ぁ-ん]")


def _agents() -> dict[str, AgentDefinition]:
    return build_agents(SETTINGS, "regimen-folfox")


def test_three_roles_by_name() -> None:
    assert AGENT_NAMES == (DATE_NORMALIZER, TERM_MAPPER, CONTRADICTION_FINDER)
    assert set(_agents()) == {"date-normalizer", "term-mapper", "contradiction-finder"}


def test_roles_have_no_tools_and_use_subagent_model_and_skill() -> None:
    for agent in _agents().values():
        assert isinstance(agent, AgentDefinition)
        assert agent.tools == []
        assert agent.model == "claude-test-sub"
        assert agent.skills == ["regimen-folfox"]


def test_roles_also_deny_emit_and_subagent_tools() -> None:
    # tools=[] が「親のツールを全部継ぐ」と解釈されても、結果の提出と孫の起動はさせない。
    # Skill は入れない（skills の先読みが Skill ツールに依るかは未検証のため）
    for agent in _agents().values():
        assert agent.disallowedTools == [
            "mcp__tsutae__emit_timeline",
            "mcp__tsutae__emit_report",
            "Agent",
            "Task",
        ]


def test_capox_skill_name_is_passed_through() -> None:
    agents = build_agents(SETTINGS, "regimen-capox")
    assert all(a.skills == ["regimen-capox"] for a in agents.values())


def test_invalid_skill_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_agents(SETTINGS, "report-format-default")
    with pytest.raises(ValueError):
        build_agents(SETTINGS, "../etc")


def test_descriptions_and_prompts_are_japanese() -> None:
    for agent in _agents().values():
        assert HIRAGANA.search(agent.description)
        assert HIRAGANA.search(agent.prompt)


@pytest.mark.parametrize(
    ("name", "words"),
    [
        (
            DATE_NORMALIZER,
            (
                "mentions",
                "entry_no",
                "source_quote",
                "date",
                "day",
                "recalled",
                "confidence",
                "record_date",
            ),
        ),
        (
            TERM_MAPPER,
            (
                "mapped",
                "entry_no",
                "source_quote",
                "term",
                "question_key",
                "status",
                "present",
                "improving",
                "absent",
            ),
        ),
        (
            CONTRADICTION_FINDER,
            (
                "contradictions",
                "entry_no",
                "date",
                "day",
                "question_key",
                "closed_answer",
                "free_text_quote",
                "answers",
            ),
        ),
    ],
)
def test_prompts_state_input_and_output_json(name: str, words: tuple[str, ...]) -> None:
    prompt = _agents()[name].prompt
    assert "入力" in prompt and "出力" in prompt and "JSON" in prompt
    for word in words:
        assert word in prompt, (name, word)


def test_term_mapper_embeds_term_list_with_question_keys() -> None:
    prompt = _agents()[TERM_MAPPER].prompt
    for item in load_terms():
        key = item.get("question_key") or "null"
        assert f"{item['term']}（question_key: {key}）" in prompt


def test_prompts_forbid_grade_and_resolution() -> None:
    agents = _agents()
    for agent in agents.values():
        assert "Grade" in agent.prompt
        assert "部分文字列" in agent.prompt
    assert "解決しない" in agents[CONTRADICTION_FINDER].prompt


def test_prompts_do_not_trip_the_detector() -> None:
    for agent in _agents().values():
        assert detect_identifiers(agent.prompt) == []
        assert detect_identifiers(agent.description) == []

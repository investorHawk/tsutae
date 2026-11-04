"""固定規則の案内（api/fixed_rules.py）。コードの閾値比較だけ。"""

from __future__ import annotations

from tsutae.api.fixed_rules import notices_for
from tsutae.config import SKILLS_DIR
from tsutae.schemas import ClosedAnswer, EntryCreate, FixedRule, RegimenSkill
from tsutae.skills import load_regimen_skill

FEVER_KEY = "fixed_rule.fever_38"


def _folfox() -> RegimenSkill:
    return load_regimen_skill("FOLFOX", SKILLS_DIR)


def _fever(temperature: float | None) -> EntryCreate:
    if temperature is None:
        answer = ClosedAnswer(question_key="fever", value="not_measured")
    else:
        answer = ClosedAnswer(
            question_key="fever", value="measured", temperature=temperature
        )
    return EntryCreate(answers=[answer])


def test_38_0_gives_fever_notice() -> None:
    assert notices_for(_fever(38.0), _folfox()) == [FEVER_KEY]


def test_above_threshold_gives_fever_notice() -> None:
    assert notices_for(_fever(39.2), _folfox()) == [FEVER_KEY]


def test_37_9_gives_no_notice() -> None:
    assert notices_for(_fever(37.9), _folfox()) == []


def test_not_measured_gives_no_notice() -> None:
    assert notices_for(_fever(None), _folfox()) == []


def test_no_fever_answer_gives_no_notice() -> None:
    entry = EntryCreate(answers=[ClosedAnswer(question_key="diarrhea", value="hard")])
    assert notices_for(entry, _folfox()) == []


def test_too_sick_and_free_text_give_no_notice() -> None:
    assert notices_for(EntryCreate(too_sick=True), _folfox()) == []
    # 自由記載の「38.5℃」は読まない（コードの比較はクローズ回答だけ）
    assert notices_for(EntryCreate(free_text="熱が38.5℃あった"), _folfox()) == []


def test_skill_without_rules_gives_no_notice() -> None:
    skill = _folfox().model_copy(update={"fixed_rules": []})
    assert notices_for(_fever(39.0), skill) == []


def test_rules_in_order_without_duplicates() -> None:
    base = _folfox()
    rules = [
        FixedRule(
            key="fever_38",
            question_key="fever",
            threshold_celsius=38.0,
            patient_string_key=FEVER_KEY,
        ),
        FixedRule(
            key="fever_37",
            question_key="fever",
            threshold_celsius=37.0,
            patient_string_key="fixed_rule.other",
        ),
        FixedRule(
            key="fever_38_dup",
            question_key="fever",
            threshold_celsius=38.0,
            patient_string_key=FEVER_KEY,
        ),
    ]
    skill = base.model_copy(update={"fixed_rules": rules})
    assert notices_for(_fever(38.4), skill) == [FEVER_KEY, "fixed_rule.other"]
    assert notices_for(_fever(37.5), skill) == ["fixed_rule.other"]


def test_does_not_mutate_arguments() -> None:
    entry = _fever(38.0)
    skill = _folfox()
    before = (entry.model_dump(), skill.model_dump())
    notices_for(entry, skill)
    assert (entry.model_dump(), skill.model_dump()) == before

"""T95: レジメンの2つ固定を外しても、FOLFOX/CAPOX の依頼文が1文字も変わらない。

評価（eval）は合成データの各コースの最終日を受診日として `build_prompt` と3役の
AgentDefinition（term-mapper の用語の一覧を含む）を使う。その全文の sha256 を T95 の
前の値で固定する。値が変わったら、評価済みの依頼文が変わったということ（eval の数字が
ずれうる）なので、直す前に先生に確かめる。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date

import pytest
from pipeline_fakes import CASE_NAMES, course_last_days, prepare_case

from tsutae.config import get_settings
from tsutae.pipeline.agents import build_agents
from tsutae.pipeline.prompt import SYSTEM_PROMPT, build_prompt

SETTINGS = replace(get_settings(), subagent_model="claude-test-sub")

# (症例, 受診日) -> build_prompt の sha256（T95 の前に測った値）
PROMPT_SHA256 = {
    ("demo_patient", "2026-10-12"): (
        "8049430037fb43ef383dc3e098edbdd7790c05415bb4fdde928114d473d689ff"
    ),
    ("demo_patient", "2026-10-26"): (
        "f3fddf8bc4da0515ab485225004e95da6b0f8ae17be86404954104d66be1362c"
    ),
    ("demo_patient", "2026-11-09"): (
        "28f58834dfe851464589a963ef9b72a48f86823010ef7be62f8d87d3b5ea44b0"
    ),
    ("eval_patient_a", "2026-09-14"): (
        "a9860978ac2e57ac7e5d6112c70619e6e8123891d2ace8839671a717a8d104e4"
    ),
    ("eval_patient_a", "2026-09-28"): (
        "8c99f2231970840e611375e0dc961f0f7efb53a3f8ce8d9391f36c61003c5706"
    ),
    ("eval_patient_b", "2026-09-07"): (
        "f5af0ed783f06e9dad03c5ea91acd6f49843c659f1638837ace1a248f3ab7416"
    ),
    ("eval_patient_b", "2026-09-21"): (
        "3eda05385cc865ecdda7e4682bf962aeaf5ce41da6acf4def763bb610bab0b43"
    ),
}
# 役 -> (prompt, description) の sha256
AGENT_SHA256 = {
    "date-normalizer": (
        "41a39394db150ee6c7387cfcbd20ce3f244630f75430acd350ccaa863973ab23",
        "476f51c9d1a040eae5c352e6a0cf38af292d02ac0ba0cf5ef37317f2712d23ac",
    ),
    "term-mapper": (
        "35a59a2f8b4915c196f4780c7612cf91324faa8b34211a52f3f4bde11b7b5a58",
        "ddc8aefc3f0bba75121c2c1db42e70219c047ab8c20e5e8edfdda4ee61aa8b4c",
    ),
    "contradiction-finder": (
        "49af90c71f565c596aa35dcfcefe4b310e7406476cf13a3af8277562e354be7b",
        "3f258f3856f294c2a99f554b0cbc1fdb3cef480fe864a1fb12b3cc28fe4ec504",
    ),
}
SYSTEM_SHA256 = "a04615813654646e64f6cc5361482f180416c3431afb35752c3bdc9dc0e21d9c"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _eval_courses() -> list[tuple[str, str]]:
    return [(n, d.isoformat()) for n in CASE_NAMES for d in course_last_days(n)]


def test_all_eval_courses_are_frozen() -> None:
    assert sorted(_eval_courses()) == sorted(PROMPT_SHA256)


@pytest.mark.parametrize("case", sorted(PROMPT_SHA256))
def test_build_prompt_unchanged(case: tuple[str, str]) -> None:
    name, visit = case
    prepared = prepare_case(name, date.fromisoformat(visit))
    assert _sha(build_prompt(prepared)) == PROMPT_SHA256[case]


@pytest.mark.parametrize("skill", ["regimen-folfox", "regimen-capox"])
def test_agent_prompts_unchanged(skill: str) -> None:
    agents = build_agents(SETTINGS, skill)
    got = {n: (_sha(a.prompt), _sha(a.description)) for n, a in agents.items()}
    assert got == AGENT_SHA256


def test_agent_prompts_unchanged_with_prepared_term_keys() -> None:
    """FOLFOX@1 の入力が持つ用語の対応（版の term_keys は無い）で作っても同じ。"""
    prepared = prepare_case("demo_patient")
    agents = build_agents(SETTINGS, "regimen-folfox", term_keys=prepared.term_keys)
    got = {n: (_sha(a.prompt), _sha(a.description)) for n, a in agents.items()}
    assert got == AGENT_SHA256


def test_system_prompt_unchanged() -> None:
    assert _sha(SYSTEM_PROMPT) == SYSTEM_SHA256

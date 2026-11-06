"""用語の一覧（ctcae_terms.json）の中身と、説明の文に古い言い方が残っていないこと。

- 一覧はこのアプリの用語の一覧。トップは note と terms、各語は term と question_key だけ
- 置き換えた語は一覧にも、Skill・form・正解ラベルにも残らない
- 外部の規準を引いているように読める文が、紙・プロンプト・Skill に出ない。ここで探す語は、
  リポジトリを文字列で検索したときに当たらないよう、分けて書く
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from tsutae import config
from tsutae.config import get_settings
from tsutae.pipeline.agents import TERM_MAPPER, build_agents
from tsutae.pipeline.prompt import SYSTEM_PROMPT
from tsutae.regimen.chat_prompt import SYSTEM_PROMPT as CHAT_SYSTEM_PROMPT
from tsutae.regimen.chat_prompt import build_turn_prompt
from tsutae.regimen.chat_types import TurnInput
from tsutae.regimen.form import FieldSources, load_builtin_form
from tsutae.regimen.render import render_regimen_skill
from tsutae.report import build_report_data, render_report_html
from tsutae.report.sample import load_demo_inputs
from tsutae.skills import read_skill_text
from tsutae.synthetic import load_terms

TERMS_PATH = config.PACKAGE_ROOT / "data" / "ctcae_terms.json"
SKILLS = ("regimen-folfox", "regimen-capox", "report-format-default")
BUILTIN_FORMS = ("regimen-folfox", "regimen-capox")
LABEL_FILES = ("demo_patient", "eval_patient_a", "eval_patient_b")

RETIRED_WORDS = (
    "JC" + "OG",
    "CT" + "CAE",
    "有害事象共通" + "用語",
    "日本語" + "訳",
    "v5" + ".0",
    "より" + "引用",
)
REPLACED_TERMS = (
    "末梢性感覚ニューロパチー",
    "錯感覚",
    "異常感覚",
    "口腔粘膜炎",
    "口腔内痛",
    "浮動性めまい",
    "口内乾燥",
    "脱毛症",
    "不眠症",
    "手掌・足底発赤知覚不全症候群",
)
NEW_TERMS = {
    "末梢神経障害": "numbness",
    "口内炎": "stomatitis",
    "口腔痛": "stomatitis",
    "めまい": None,
    "口腔内乾燥感": None,
    "脱毛": None,
    "不眠": None,
    "手足症候群": "hand_foot",
}


def _sample_html() -> str:
    sample = load_demo_inputs(fallback=False)
    data = build_report_data(**sample.build_kwargs())
    return render_report_html(data, questions=list(sample.regimen_skill.questions))


def _assert_no_retired_words(text: str) -> None:
    assert [word for word in RETIRED_WORDS if word in text] == []


# ---------------------------------------------------------------------------
# 一覧の形
# ---------------------------------------------------------------------------


def test_file_has_only_note_and_terms() -> None:
    raw = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    assert set(raw) == {"note", "terms"}
    assert {frozenset(item) for item in raw["terms"]} == {
        frozenset({"term", "question_key"})
    }


def test_list_has_32_unique_terms() -> None:
    counts = Counter(item["term"] for item in load_terms())
    assert len(counts) == 32
    assert [term for term, count in counts.items() if count > 1] == []


@pytest.mark.parametrize(("term", "key"), NEW_TERMS.items())
def test_new_terms_keep_their_question_keys(term: str, key: str | None) -> None:
    assert {t["term"]: t["question_key"] for t in load_terms()}[term] == key


def test_replaced_terms_are_gone_from_the_list() -> None:
    names = {item["term"] for item in load_terms()}
    assert names.isdisjoint(REPLACED_TERMS)


# ---------------------------------------------------------------------------
# form・Skill・正解ラベル
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", BUILTIN_FORMS)
def test_builtin_form_numbness_row_has_one_term(name: str) -> None:
    form = load_builtin_form(name)
    [row] = [r for r in form.side_effects if r.question_key == "numbness"]
    assert list(row.ctcae_terms) == ["末梢神経障害"]


@pytest.mark.parametrize("name", BUILTIN_FORMS)
def test_rendered_skill_table_uses_new_terms(name: str) -> None:
    text = render_regimen_skill(load_builtin_form(name), 1)
    assert "| 末梢神経障害 | numbness |" in text
    assert "| 口内炎／口腔痛 | stomatitis |" in text
    assert [term for term in REPLACED_TERMS if term in text] == []


def test_capox_table_uses_hand_foot_term() -> None:
    text = render_regimen_skill(load_builtin_form("regimen-capox"), 1)
    assert "| 手足症候群 | hand_foot |" in text


@pytest.mark.parametrize("stem", LABEL_FILES)
def test_labels_use_only_terms_in_the_list(stem: str) -> None:
    path: Path = config.SYNTHETIC_DIR / f"labels_{stem}.json"
    text = path.read_text(encoding="utf-8")
    assert [term for term in REPLACED_TERMS if term in text] == []
    names = {item["term"] for item in load_terms()}
    used = {
        event["term"]
        for label in json.loads(text)["labels"]
        for event in label["events"]
    }
    assert used <= names


# ---------------------------------------------------------------------------
# 紙・プロンプト・Skill の説明の文
# ---------------------------------------------------------------------------


def test_report_margin_is_the_fixed_sentence() -> None:
    html = _sample_html()
    assert (
        "<p>用語名はこのアプリの用語の一覧から AI が当てはめた候補で、医師が確定する。"
        "重さの判定・原因の推測・助言はしていない。</p>"
    ) in html
    _assert_no_retired_words(html)


def test_conversion_prompts_have_no_retired_words() -> None:
    settings = replace(get_settings(), subagent_model="claude-test-sub")
    agents = build_agents(settings, "regimen-folfox")
    _assert_no_retired_words(SYSTEM_PROMPT)
    for agent in agents.values():
        _assert_no_retired_words(agent.prompt)
        _assert_no_retired_words(agent.description)
    assert "## 用語の一覧\n" in agents[TERM_MAPPER].prompt


def test_chat_prompt_has_no_retired_words() -> None:
    turn = TurnInput(
        draft_id=1,
        form=load_builtin_form("regimen-folfox"),
        sources=FieldSources({}),
        library=(),
    )
    _assert_no_retired_words(CHAT_SYSTEM_PROMPT)
    prompt = build_turn_prompt(turn, "FOLFOX を見直す")
    _assert_no_retired_words(prompt)
    assert "## 用語の一覧（" in prompt


@pytest.mark.parametrize("name", SKILLS)
def test_skills_have_no_retired_words(name: str) -> None:
    _assert_no_retired_words(read_skill_text(name, skills_dir=config.SKILLS_DIR))

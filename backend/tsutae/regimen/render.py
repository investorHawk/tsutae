"""フォーム → SKILL.md（Jinja2。spec 9.1・architecture 9c）。

- `render_regimen_skill(form, version)` は純関数（DB・部品集を見ない）。同じ値なら同じ文字列
- FOLFOX/CAPOX@1 は `regimen_forms/*.json` から描いて今の SKILL.md とバイト一致する（テスト）
- frontmatter の鍵は v1.0 のまま。任意の `display_name`（識別名と違うときだけ）と
  `term_keys`（用語→質問の対応のうち ctcae_terms.json と違うものだけ）を足す
- 描く前に validate_complete_form、描いた後に strict の validate_skill_text と
  frontmatter の読み戻しを必ず通す。AI に SKILL.md を書かせない
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from tsutae.regimen.form import (
    ContradictionExample,
    QuestionRow,
    RegimenForm,
    RegimenProse,
)
from tsutae.regimen.schedule import (
    build_schedule,
    date_rows,
    schedule_keys,
    schedule_lines,
)
from tsutae.regimen.text_checks import RegimenFormError
from tsutae.regimen.validate import DESCRIPTION_TEMPLATE, validate_complete_form
from tsutae.skills.loader import (
    SkillValidationError,
    parse_skill_md,
    validate_skill_text,
)
from tsutae.synthetic import load_terms, term_question_keys

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_NAME = "regimen_skill.md.j2"
SKILL_PREFIX = "regimen-"
FEVER_RULE = {
    "key": "fever_38",
    "threshold_celsius": 38.0,
    "patient_string_key": "fixed_rule.fever_38",
}
# まとめた質問の行（§5）で、既知の質問は今の文のまま（FOLFOX/CAPOX@1 の並び）
KNOWN_COMBINED = (
    ("nausea_appetite", "吐き気・食欲"),
    ("numbness", "しびれ・冷感"),
    ("stomatitis", "口内炎・口の中の痛み"),
)
# §2「〜から」の例の行き先。点滴の日が2つ以上なら表の行（最も近い点滴の日の次の日）に合わせる
FROM_EXAMPLE_SINGLE = "Day2"
FROM_EXAMPLE_MULTI = "上の点滴の日の次の日。Day1 なら Day2"
KNOWN_COMBINED_EXAMPLE = (
    "nausea_appetite「ある」で、自由記載では悪心が absent・食欲不振が present → "
    "食い違いではない"
)


@dataclass(frozen=True)
class _TermRow:
    phrases: str
    terms: str
    key: str


@dataclass(frozen=True)
class _Combined:
    items: str
    example: str


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


@lru_cache(maxsize=1)
def global_term_keys() -> dict[str, str | None]:
    """ctcae_terms.json の全体の対応（用語 → 質問 key）。"""
    return term_question_keys(load_terms())


def skill_name_for(form: RegimenForm) -> str:
    """`regimen-` + 識別名の小文字（例: RAM-WPTX → regimen-ram-wptx）。"""
    if not form.basic.code:
        raise ValueError("識別名（basic.code）が無い")
    return SKILL_PREFIX + form.basic.code.lower()


# ---------------------------------------------------------------------------
# 本文に入る値
# ---------------------------------------------------------------------------


def term_keys_for_form(form: RegimenForm) -> dict[str, str | None]:
    """フォームの用語→質問のうち、全体の対応と違うもの（並びは副作用の行の順）。"""
    known = global_term_keys()
    return {
        term: row.question_key
        for row in form.side_effects
        for term in row.ctcae_terms
        if known.get(term) != row.question_key
    }


def _questions_by_key(form: RegimenForm) -> dict[str, QuestionRow]:
    return {q.key: q for q in form.questions if q.key is not None}


def _combined_example(form: RegimenForm, key: str) -> str:
    if key == "nausea_appetite":
        return KNOWN_COMBINED_EXAMPLE
    terms = [
        t for r in form.side_effects if r.question_key == key for t in r.ctcae_terms
    ]
    if len(terms) < 2:
        return f"{key}「ある」で、自由記載にその症状が present → 食い違いではない"
    return (
        f"{key}「ある」で、自由記載では{terms[0]}が absent・{terms[1]}が present → "
        "食い違いではない"
    )


def _combined(form: RegimenForm) -> _Combined | None:
    """まとめた質問の行。既知の3つは今の文、それ以外は用語を2語以上持つ3択の質問。"""
    by_key = _questions_by_key(form)
    known = dict(KNOWN_COMBINED)
    keys = [key for key, _ in KNOWN_COMBINED if key in by_key]
    items = [f"{key}＝{known[key]}" for key in keys]
    for key, q in by_key.items():
        if key in known or q.answer_type != "three_level":
            continue
        rows = [r for r in form.side_effects if r.question_key == key]
        if sum(len(r.ctcae_terms) for r in rows) < 2:
            continue
        keys.append(key)
        items.append(f"{key}＝{'・'.join(p for r in rows for p in r.phrases)}")
    if not items:
        return None
    return _Combined("、".join(items), _combined_example(form, keys[0]))


def _default_example(form: RegimenForm) -> ContradictionExample | None:
    by_key = _questions_by_key(form)
    for row in form.side_effects:
        q = by_key.get(row.question_key) if row.question_key else None
        if q is not None and q.answer_type == "three_level" and row.phrases:
            return ContradictionExample(
                closed_label=q.label or "",
                question_key=row.question_key or "",
                quote=row.phrases[0],
            )
    return None


def _improving(form: RegimenForm, prose: RegimenProse) -> str:
    examples = prose.improving_examples
    if examples is None:
        first = form.side_effects[0].phrases[0]
        examples = [f"{first}はだいぶ楽", "昨日よりまし"]
    return "".join(f"「{e}」" for e in examples)


def _pump_sentence(form: RegimenForm, prose: RegimenProse) -> str:
    if prose.pump_sentence is not None:
        return prose.pump_sentence
    pump = next((d for d in form.drugs if d.route == "pump"), None)
    name = pump.name if pump is not None else ""
    return (
        f"Day1 に外来で点滴し、続けて{name}を入れる持続ポンプ（携帯型）をつけて帰宅する"
    )


def _notes(text: str) -> str:
    """各行の末尾の空白と前後の空行を落とす（CR は検査で拒否済み。改行は LF だけ）。"""
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip("\n")


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------


def _fever_key(form: RegimenForm) -> str:
    return next(
        q.key for q in form.questions if q.answer_type == "temperature" and q.key
    )


def expected_frontmatter(form: RegimenForm, version: int) -> dict[str, Any]:
    """描いた SKILL.md の frontmatter を YAML で読み戻したときの値（読み戻しの照合用）。"""
    basic = form.basic
    display = basic.display_name or ""
    schedule = build_schedule(form)
    meta: dict[str, Any] = {
        "name": skill_name_for(form),
        "description": DESCRIPTION_TEMPLATE.format(v=display),
        "version": version,
        "regimen": basic.code,
        "cycle_days": basic.cycle_days,
        "pump_removal_day": schedule.pump_removal_day,
        "questions": [
            {"key": q.key, "text": q.text, "answer_type": q.answer_type}
            for q in form.questions
        ],
        "fixed_rules": [{**FEVER_RULE, "question_key": _fever_key(form)}],
    }
    if display != basic.code:
        meta["display_name"] = display
    term_keys = term_keys_for_form(form)
    if term_keys:
        meta["term_keys"] = term_keys
    return meta


def _context(form: RegimenForm, version: int) -> dict[str, Any]:
    prose = form.prose or RegimenProse()
    basic = form.basic
    display = basic.display_name or ""
    schedule = build_schedule(form)
    removal = schedule.pump_removal_day
    return {
        "name": skill_name_for(form),
        "description": DESCRIPTION_TEMPLATE.format(v=display),
        "version": version,
        "code": basic.code,
        "display_name": display,
        "display_name_key": display if display != basic.code else None,
        "cycle_days": basic.cycle_days,
        "pump_removal_day": "null" if removal is None else removal,
        "questions": form.questions,
        "fever_key": _fever_key(form),
        "term_keys": [
            (term, "null" if key is None else key)
            for term, key in term_keys_for_form(form).items()
        ],
        "intro_note": prose.intro_note,
        "schedule_lines": schedule_lines(
            form,
            schedule,
            cycle_note=prose.cycle_note,
            day1_note=prose.day1_note,
            pump_sentence=_pump_sentence(form, prose),
            no_pump_note=prose.no_pump_note,
            oral_note=prose.oral_note,
        ),
        "schedule_keys": schedule_keys(schedule),
        "date_rows": date_rows(schedule, display),
        "from_example": (
            FROM_EXAMPLE_MULTI
            if len(schedule.infusion_days) >= 2
            else FROM_EXAMPLE_SINGLE
        ),
        "term_rows": [
            _TermRow(
                "、".join(row.phrases),
                "／".join(row.ctcae_terms),
                row.question_key or "null",
            )
            for row in form.side_effects
        ],
        "improving": _improving(form, prose),
        "example": prose.contradiction_example or _default_example(form),
        "combined": _combined(form),
        "notes": _notes(form.notes),
    }


# ---------------------------------------------------------------------------
# 公開
# ---------------------------------------------------------------------------


def render_regimen_skill(form: RegimenForm, version: int) -> str:
    """フォームと版から SKILL.md の全文を描く。

    フォームが検査に掛かれば `RegimenFormError`（欄の id つき）。描いた結果が
    strict の検査・読み戻しに通らなければ `SkillValidationError`（描画の不具合）。
    """
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version は 1 以上の整数")
    issues = validate_complete_form(form)
    if issues:
        raise RegimenFormError(issues)
    text = _environment().get_template(TEMPLATE_NAME).render(**_context(form, version))
    name = skill_name_for(form)
    validate_skill_text(name, text)
    meta, _body = parse_skill_md(text)
    if meta != expected_frontmatter(form, version):
        raise SkillValidationError("round_trip", "frontmatter を読み戻すと値が違う")
    return text

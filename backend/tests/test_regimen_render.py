"""フォーム → SKILL.md の描画（T91。spec 9.1・architecture 9c）。"""

from __future__ import annotations

import difflib

import pytest
from regimen_fixtures import EXTRA_REGIMENS, extra_form

from tsutae import config
from tsutae.regimen import (
    RegimenForm,
    RegimenFormError,
    load_builtin_form,
    render_regimen_skill,
    skill_name_for,
)
from tsutae.schemas import RegimenSkill
from tsutae.skills import parse_skill_md, read_skill_text, validate_skill_text

V10_KEYS = {
    "name",
    "description",
    "version",
    "regimen",
    "cycle_days",
    "pump_removal_day",
    "questions",
    "fixed_rules",
}
OPTIONAL_KEYS = {"display_name", "term_keys"}


def _diff(expected: str, actual: str) -> str:
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            "SKILL.md",
            "rendered",
        )
    )


# ---------------------------------------------------------------------------
# バイト一致（評価済みの版は描き方を変えても1バイトも変わらない）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["regimen-folfox", "regimen-capox"])
def test_builtin_form_renders_the_current_skill_byte_for_byte(name: str) -> None:
    expected = read_skill_text(name, skills_dir=config.SKILLS_DIR)
    actual = render_regimen_skill(load_builtin_form(name), 1)
    assert actual == expected, _diff(expected, actual)
    assert actual.encode("utf-8") == expected.encode("utf-8")


@pytest.mark.parametrize("name", ["regimen-folfox", "regimen-capox"])
def test_builtin_form_has_no_optional_frontmatter_keys(name: str) -> None:
    meta, _ = parse_skill_md(render_regimen_skill(load_builtin_form(name), 1))
    assert set(meta) == V10_KEYS


def test_version_is_written_to_frontmatter() -> None:
    text = render_regimen_skill(load_builtin_form("regimen-folfox"), 7)
    skill = validate_skill_text("regimen-folfox", text)
    assert skill.version == 7


@pytest.mark.parametrize("version", [0, -1, True, 1.0, "1"])
def test_bad_version_is_rejected(version: object) -> None:
    with pytest.raises(ValueError):
        render_regimen_skill(load_builtin_form("regimen-folfox"), version)  # type: ignore[arg-type]


def test_render_is_deterministic() -> None:
    form = load_builtin_form("regimen-capox")
    assert render_regimen_skill(form, 1) == render_regimen_skill(form, 1)


# ---------------------------------------------------------------------------
# §5 の3レジメン
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(EXTRA_REGIMENS))
def test_extra_regimens_render_and_pass_strict_validation(key: str) -> None:
    form = extra_form(key)
    text = render_regimen_skill(form, 1)
    name = skill_name_for(form)
    skill = validate_skill_text(name, text)
    assert isinstance(skill, RegimenSkill)
    meta, _ = parse_skill_md(text)
    assert V10_KEYS <= set(meta) <= V10_KEYS | OPTIONAL_KEYS
    assert meta["display_name"] == form.basic.display_name
    assert skill.regimen == form.basic.code
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_skill_names_of_extra_regimens() -> None:
    assert skill_name_for(extra_form("ram_wptx")) == "regimen-ram-wptx"
    assert skill_name_for(extra_form("folfiri_bv")) == "regimen-folfiri-bv"
    assert skill_name_for(extra_form("lonsurf_bv")) == "regimen-lonsurf-bv"


def _body(key: str) -> str:
    _, body = parse_skill_md(render_regimen_skill(extra_form(key), 1))
    return body


def _rows(body: str) -> list[list[str]]:
    return [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in body.splitlines()
        if line.startswith("|")
    ]


def _row(body: str, left: str) -> list[str]:
    found = [r for r in _rows(body) if r[0] == left]
    assert len(found) == 1, (left, _rows(body))
    return found[0]


def test_ram_infusion_day_is_the_nearest_of_day1_8_15() -> None:
    body = _body("ram_wptx")
    row = _row(body, "点滴の日・投与日・病院で点滴した日")
    assert "記録日以前で最も近い点滴の日（Day1・8・15）" in row[1]
    assert "confidence を下げる" in row[1]
    nxt = _row(body, "点滴の次の日・点滴の翌日")
    assert "Day2・9・16" in nxt[1]
    assert "confidence を下げる" in nxt[1]
    assert "Day1・8・15" in body.split("## 2.")[0]  # 投与スケジュールの節にも出る


def test_ram_has_no_pump_row_and_no_oral_rows() -> None:
    body = _body("ram_wptx")
    row = _row(body, "「ポンプ」が出てくる表現")
    assert row[1].startswith("RAM＋wPTX にポンプは無い")
    assert "飲み薬" not in body.split("## 3.")[0]
    assert "pump_removal_date`・" not in body


def test_lonsurf_has_oral_rest_rows() -> None:
    body = _body("lonsurf_bv")
    rest = _row(body, "飲み薬が休みの日・休薬に入った日")
    assert "Day6・13" in rest[1]
    end = _row(body, "飲み薬が終わった日・最後に飲んだ日")
    assert "Day5・12" in end[1]
    restart = _row(body, "飲み薬を再開した日・また飲み始めた日")
    assert restart[1].startswith("Day8")
    start = _row(
        body, "飲み薬を始めた日"
    )  # 点滴の日が2つあるので Day1 の行にまとめない
    assert start[1] == "Day1"
    assert (
        "Day1 の朝から飲み薬（トリフルリジン・チピラシル）を1日2回、10日間飲む" in body
    )
    assert "Day1〜Day5・Day8〜Day12 が内服、Day6〜Day7・Day13〜Day28 が休薬" in body


def test_folfiri_has_pump_rows_like_folfox() -> None:
    body = _body("folfiri_bv")
    assert _row(body, "ポンプを外した日・ポンプを抜いた日")[1] == "Day3（ポンプ抜去日）"
    assert _row(body, "ポンプを外した次の日")[1] == "Day4"
    assert _row(body, "点滴の日・投与日・病院で点滴した日")[1] == "Day1（実投与日）"
    assert "**Day3 にポンプを外す**" in body
    assert "フルオロウラシル（46時間）" in body


def test_term_keys_are_only_the_differences_from_the_global_map() -> None:
    meta, _ = parse_skill_md(render_regimen_skill(extra_form("ram_wptx"), 1))
    assert meta["term_keys"] == {
        "末梢神経障害": "neuropathy",
        "疲労": "fatigue",
        "倦怠感": "fatigue",
        "鼻出血": "bleeding",
    }
    skill = validate_skill_text(
        "regimen-ram-wptx", render_regimen_skill(extra_form("ram_wptx"), 1)
    )
    assert skill.term_keys == meta["term_keys"]


def test_question_labels_and_target_are_not_written() -> None:
    form = extra_form("ram_wptx")
    text = render_regimen_skill(form, 1)
    meta, _ = parse_skill_md(text)
    for q in meta["questions"]:
        assert set(q) == {"key", "text", "answer_type"}
    assert "胃がん" not in text


def test_fixed_rule_points_to_the_temperature_question() -> None:
    skill = validate_skill_text(
        "regimen-lonsurf-bv", render_regimen_skill(extra_form("lonsurf_bv"), 1)
    )
    assert [r.model_dump() for r in skill.fixed_rules] == [
        {
            "key": "fever_38",
            "question_key": "fever",
            "threshold_celsius": 38.0,
            "patient_string_key": "fixed_rule.fever_38",
        }
    ]


def test_combined_question_line_uses_only_present_keys() -> None:
    body = _body("lonsurf_bv")
    line = next(x for x in body.splitlines() if "複数の症状をまとめている" in x)
    assert "nausea_appetite＝吐き気・食欲" in line
    assert "numbness" not in line and "stomatitis" not in line
    assert "fatigue＝だるい・疲れやすい" in line


def test_term_table_matches_ctcae_terms_for_extra_regimens() -> None:
    from tsutae.synthetic import load_terms

    known = {t["term"] for t in load_terms()}
    for key in EXTRA_REGIMENS:
        rows = [
            r
            for r in _rows(_body(key))
            if len(r) == 3 and r[1] not in ("term の候補", "---")
        ]
        assert rows
        for _example, candidates, _qkey in rows:
            for term in candidates.split("／"):
                assert term in known, term


# ---------------------------------------------------------------------------
# 補足の指示
# ---------------------------------------------------------------------------


def test_notes_section_is_rendered_last_when_not_empty() -> None:
    text = render_regimen_skill(extra_form("ram_wptx"), 1)
    assert text.endswith(
        "\n\n## 10. 補足の指示（施設の決まり）\n\n"
        "手足のむくみは用語の一覧に無いので、出来事にせず引用に残す\n"
    )


def test_notes_section_is_absent_when_empty() -> None:
    text = render_regimen_skill(extra_form("folfiri_bv"), 1)
    assert "## 10." not in text
    assert text.endswith(
        "`fixed_rules` の `question_key` は `questions` にある key だけ\n"
    )


def test_multiline_notes_are_normalized_to_one_trailing_newline() -> None:
    data = EXTRA_REGIMENS["folfiri_bv"]()
    data["notes"] = "1行目\n2行目\n\n"
    text = render_regimen_skill(RegimenForm.model_validate(data), 1)
    assert text.endswith("## 10. 補足の指示（施設の決まり）\n\n1行目\n2行目\n")


def test_default_prose_for_new_regimen() -> None:
    body = _body("folfiri_bv")
    assert "- 1コースは14日。**Day1 = 実投与日**（外来で点滴した日）" in body
    assert "「下痢はだいぶ楽」「昨日よりまし」" in body
    assert "クローズ「下痢 なし」＋自由記載「下痢」" in body
    assert "- 症例は全て合成（架空）" in body


# ---------------------------------------------------------------------------
# 描けない形
# ---------------------------------------------------------------------------


def test_incomplete_form_is_not_rendered() -> None:
    data = EXTRA_REGIMENS["ram_wptx"]()
    data["basic"]["cycle_days"] = None
    with pytest.raises(RegimenFormError) as exc:
        render_regimen_skill(RegimenForm.model_validate(data), 1)
    assert "basic.cycle_days" in {i.field_id for i in exc.value.issues}


def test_form_with_bad_values_is_not_rendered() -> None:
    data = EXTRA_REGIMENS["ram_wptx"]()
    data["drugs"][0]["name"] = "パクリタキセル 80mg/m2"
    with pytest.raises(RegimenFormError) as exc:
        render_regimen_skill(RegimenForm.model_validate(data), 1)
    assert [(i.field_id, i.code) for i in exc.value.issues] == [
        ("drugs.d-ptx.name", "dose")
    ]


def test_term_keys_can_unlink_a_globally_linked_term() -> None:
    """全体の対応では diarrhea の「下痢」も、質問が無いレジメンでは null で外せる。"""
    data = EXTRA_REGIMENS["folfiri_bv"]()
    data["questions"] = [q for q in data["questions"] if q["key"] != "diarrhea"]
    for row in data["side_effects"]:
        if row["question_key"] == "diarrhea":
            row["question_key"] = None
    text = render_regimen_skill(RegimenForm.model_validate(data), 1)
    meta, _ = parse_skill_md(text)
    assert meta["term_keys"]["下痢"] is None
    assert "  下痢: null\n" in text
    skill = validate_skill_text("regimen-folfiri-bv", text)
    assert skill.term_keys is not None and skill.term_keys["下痢"] is None


# ---------------------------------------------------------------------------
# 検証者の指摘（例の文・行のまとめ方・休薬の行・読み戻し）
# ---------------------------------------------------------------------------

FROM_EXAMPLE_SINGLE = "（例:「点滴の次の日から下痢」→ Day2）"
FROM_EXAMPLE_MULTI = (
    "（例:「点滴の次の日から下痢」→ 上の点滴の日の次の日。Day1 なら Day2）"
)


@pytest.mark.parametrize("key", ["folfiri_bv"])
def test_from_example_is_day2_when_one_infusion_day(key: str) -> None:
    body = _body(key)
    assert FROM_EXAMPLE_SINGLE in body
    assert FROM_EXAMPLE_MULTI not in body


@pytest.mark.parametrize("key", ["ram_wptx", "lonsurf_bv"])
def test_from_example_follows_the_nearest_infusion_day(key: str) -> None:
    """点滴の日が2つ以上なら「→ Day2」と決めつけない（表の行と食い違わない）。"""
    body = _body(key)
    assert FROM_EXAMPLE_MULTI in body
    assert FROM_EXAMPLE_SINGLE not in body


def test_pump_removed_on_day1_merges_its_next_day_into_the_day2_row() -> None:
    data = EXTRA_REGIMENS["folfiri_bv"]()
    data["drugs"][4]["days"] = [{"start": 1, "end": 1}]
    form = RegimenForm.model_validate(data)
    text = render_regimen_skill(form, 1)
    _, body = parse_skill_md(text)
    row = _row(body, "点滴の次の日・点滴の翌日・ポンプを外した次の日")
    assert row[1] == "Day2"
    assert _row(body, "ポンプを外した日・ポンプを抜いた日")[1] == "Day1（ポンプ抜去日）"
    assert validate_skill_text("regimen-folfiri-bv", text).pump_removal_day == 1


def test_folfiri_pump_removal_day_is_written_to_frontmatter() -> None:
    text = render_regimen_skill(extra_form("folfiri_bv"), 1)
    assert "\npump_removal_day: 3\n" in text
    assert validate_skill_text("regimen-folfiri-bv", text).pump_removal_day == 3


def test_ram_pump_removal_day_is_null() -> None:
    text = render_regimen_skill(extra_form("ram_wptx"), 1)
    assert "\npump_removal_day: null\n" in text
    assert validate_skill_text("regimen-ram-wptx", text).pump_removal_day is None


def test_single_oral_range_to_the_end_of_cycle_has_no_rest_row() -> None:
    data = EXTRA_REGIMENS["lonsurf_bv"]()
    data["drugs"][0]["days"] = [{"start": 1, "end": 28}]
    _, body = parse_skill_md(render_regimen_skill(RegimenForm.model_validate(data), 1))
    assert _row(body, "飲み薬が終わった日・最後に飲んだ日")[1].startswith("Day28")
    left = {r[0] for r in _rows(body)}
    assert not any("休薬" in x or "休み" in x for x in left)
    assert "が休薬" not in body.split("## 2.")[0]


def test_last_oral_range_to_the_end_of_cycle_drops_only_that_rest_start() -> None:
    data = EXTRA_REGIMENS["lonsurf_bv"]()
    data["drugs"][0]["days"] = [{"start": 1, "end": 5}, {"start": 8, "end": 28}]
    _, body = parse_skill_md(render_regimen_skill(RegimenForm.model_validate(data), 1))
    rest = _row(body, "飲み薬が休みの日・休薬に入った日")
    assert rest[1].startswith("Day6（")
    assert "Day6〜Day7 が休薬" in body


def test_round_trip_mismatch_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from tsutae.regimen import render
    from tsutae.skills import SkillValidationError

    monkeypatch.setattr(render, "expected_frontmatter", lambda form, version: {})
    with pytest.raises(SkillValidationError) as exc:
        render_regimen_skill(extra_form("ram_wptx"), 1)
    assert "round_trip" in str(exc.value)


@pytest.mark.parametrize("code", ["NO", "NULL"])
def test_yaml_reserved_code_is_rejected_with_field_id(code: str) -> None:
    data = EXTRA_REGIMENS["ram_wptx"]()
    data["basic"]["code"] = code
    with pytest.raises(RegimenFormError) as exc:
        render_regimen_skill(RegimenForm.model_validate(data), 1)
    assert ("basic.code", "yaml") in {(i.field_id, i.code) for i in exc.value.issues}

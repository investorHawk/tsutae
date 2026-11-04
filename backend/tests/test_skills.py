"""tsutae.skills（SKILL.md のローダーとバリデータ）のテスト。"""

from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from tsutae import config
from tsutae.schemas import RegimenSkill, ReportFormatSkill
from tsutae.skills import (
    MAX_SKILL_CHARS,
    SKILL_NAME_PATTERN,
    SkillFormatError,
    SkillValidationError,
    is_valid_skill_name,
    load_regimen_skill,
    load_report_skill,
    load_skill,
    parse_skill_md,
    read_skill_text,
    skill_path,
    validate_skill_text,
)

REAL_SKILLS = ("regimen-folfox", "regimen-capox", "report-format-default")

FOLFOX_QUESTIONS = [
    (
        "numbness",
        "手足のしびれや冷たいものがさわりにくい感じはありましたか",
        "three_level",
    ),
    ("diarrhea", "下痢はありましたか", "three_level"),
    ("stomatitis", "口の中の痛みや口内炎はありましたか", "three_level"),
    ("nausea_appetite", "吐き気や食欲の落ち込みはありましたか", "three_level"),
    ("fever", "熱を測りましたか", "temperature"),
]
HAND_FOOT_TEXT = "手のひらや足の裏の赤み・痛み・ひび割れはありましたか"

VALID_REGIMEN_TEXT = """---
name: regimen-test
description: テスト用のレジメン
version: 1
regimen: FOLFOX
cycle_days: 14
pump_removal_day: 3
questions:
  - {key: diarrhea, text: 下痢はありましたか, answer_type: three_level}
  - {key: fever, text: 熱を測りましたか, answer_type: temperature}
fixed_rules:
  - {key: fever_38, question_key: fever, threshold_celsius: 38.0, patient_string_key: fixed_rule.fever_38}
---
# 本文

テスト用の本文。
"""


def _replace_line(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


def _write_skill(skills_dir: Path, name: str, text: str) -> Path:
    target = skills_dir / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# 実ファイル
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", REAL_SKILLS)
def test_real_skill_files_pass_validation(name: str) -> None:
    skill = load_skill(name, skills_dir=config.SKILLS_DIR)
    assert skill.name == name
    assert skill.version >= 1
    assert skill.skill_version == f"{name}@{skill.version}"


@pytest.mark.parametrize("name", REAL_SKILLS)
def test_real_skill_files_are_readable_as_claude_code_skills(name: str) -> None:
    meta, body = parse_skill_md(read_skill_text(name, skills_dir=config.SKILLS_DIR))
    # Claude Code の Skill は name（英小文字・数字・ハイフン、64字以内）と description が必須
    assert meta["name"] == name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", meta["name"])
    assert isinstance(meta["description"], str)
    assert 0 < len(meta["description"]) <= 1024
    assert body.strip(), "本文（自然言語の指示）が空"
    assert "---" not in body.splitlines()[0]


def test_default_skills_dir_comes_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TSUTAE_SKILLS_DIR", raising=False)
    assert skill_path("regimen-folfox") == (
        config.SKILLS_DIR / "regimen-folfox" / "SKILL.md"
    )
    assert isinstance(load_skill("regimen-folfox"), RegimenSkill)


def test_folfox_questions_match_spec_4_2() -> None:
    skill = load_regimen_skill("FOLFOX", skills_dir=config.SKILLS_DIR)
    assert skill.name == "regimen-folfox"
    assert skill.regimen == "FOLFOX"
    assert skill.cycle_days == 14
    assert skill.pump_removal_day == 3
    got = [(q.key, q.text, q.answer_type) for q in skill.questions]
    assert got == FOLFOX_QUESTIONS


def test_folfox_fixed_rule_fever_38() -> None:
    skill = load_regimen_skill("FOLFOX", skills_dir=config.SKILLS_DIR)
    assert len(skill.fixed_rules) == 1
    rule = skill.fixed_rules[0]
    assert rule.key == "fever_38"
    assert rule.question_key == "fever"
    assert rule.threshold_celsius == 38.0
    assert rule.patient_string_key == "fixed_rule.fever_38"


def test_capox_has_hand_foot_and_three_week_cycle() -> None:
    skill = load_regimen_skill("CAPOX", skills_dir=config.SKILLS_DIR)
    assert skill.name == "regimen-capox"
    assert skill.regimen == "CAPOX"
    assert skill.cycle_days == 21
    assert skill.pump_removal_day is None
    by_key = {q.key: q for q in skill.questions}
    assert set(by_key) == {k for k, _, _ in FOLFOX_QUESTIONS} | {"hand_foot"}
    assert len(skill.questions) == 6
    assert by_key["hand_foot"].text == HAND_FOOT_TEXT
    assert by_key["hand_foot"].answer_type == "three_level"
    # FOLFOX と共通の質問は文言も同じ
    for key, text, answer_type in FOLFOX_QUESTIONS:
        assert by_key[key].text == text
        assert by_key[key].answer_type == answer_type
    assert [
        (r.key, r.question_key, r.threshold_celsius) for r in skill.fixed_rules
    ] == [("fever_38", "fever", 38.0)]
    assert skill.fixed_rules[0].patient_string_key == "fixed_rule.fever_38"


@pytest.mark.parametrize("regimen", ["FOLFOX", "CAPOX"])
def test_fixed_rule_strings_exist_in_patient_strings(regimen: str) -> None:
    strings = json.loads(config.PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))
    skill = load_regimen_skill(regimen, skills_dir=config.SKILLS_DIR)
    for rule in skill.fixed_rules:
        assert rule.patient_string_key in strings


def test_report_format_default_values() -> None:
    skill = load_report_skill(skills_dir=config.SKILLS_DIR)
    assert isinstance(skill, ReportFormatSkill)
    assert skill.name == "report-format-default"
    assert skill.sections == ["header", "attention", "grid", "per_symptom", "quotes"]
    assert skill.show_previous_course is True
    assert skill.show_temperature_row is True
    assert skill.quotes_max_items == 30
    assert skill.low_confidence_threshold == 0.6
    assert skill.fever_attention_celsius == 37.5


@pytest.mark.parametrize("name", ["regimen-folfox", "regimen-capox"])
def test_regimen_body_carries_the_conversion_rules(name: str) -> None:
    _, body = parse_skill_md(read_skill_text(name, skills_dir=config.SKILLS_DIR))
    for phrase in (
        "点滴の次の日",
        "Day2",
        "記録日",
        "recalled",
        "absent",
        "improving",
        "CTCAE v5.0",
        "部分文字列",
        "解決しない",
        # §5 食い違い: 改善中もクローズ「なし」と食い違う／まとめた質問は全部 absent のときだけ
        "improving としている場合も食い違い",
        "全部 absent のときだけ食い違い",
        "nausea_appetite＝吐き気・食欲",
    ):
        assert phrase in body, phrase


def test_folfox_body_describes_pump_schedule() -> None:
    _, body = parse_skill_md(
        read_skill_text("regimen-folfox", skills_dir=config.SKILLS_DIR)
    )
    for phrase in ("46時間", "ポンプを外した日", "Day3"):
        assert phrase in body, phrase


@pytest.mark.parametrize("name", ["regimen-folfox", "regimen-capox"])
def test_regimen_body_term_table_matches_ctcae_terms(name: str) -> None:
    """本文の「term の候補」表は ctcae_terms.json の用語名と question_key に一致する。"""
    terms_path = config.PACKAGE_ROOT / "data" / "ctcae_terms.json"
    terms = json.loads(terms_path.read_text(encoding="utf-8"))["terms"]
    known = {t["term"]: t["question_key"] for t in terms}
    skill = load_skill(name, skills_dir=config.SKILLS_DIR)
    question_keys = {q.key for q in skill.questions}
    _, body = parse_skill_md(read_skill_text(name, skills_dir=config.SKILLS_DIR))
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in body.splitlines()
        if line.startswith("|")
    ]
    mapped = [
        r for r in rows if len(r) == 3 and (r[2] in question_keys or r[2] == "null")
    ]
    assert mapped, "term の候補の表が無い"
    for _example, candidates, key in mapped:
        for term in candidates.split("／"):
            assert term in known, term
            assert known[term] == (None if key == "null" else key), term


# ---------------------------------------------------------------------------
# parse_skill_md
# ---------------------------------------------------------------------------


def test_parse_returns_frontmatter_and_body() -> None:
    meta, body = parse_skill_md(VALID_REGIMEN_TEXT)
    assert meta["name"] == "regimen-test"
    assert meta["version"] == 1
    assert meta["questions"][0]["key"] == "diarrhea"
    assert body.startswith("# 本文")
    assert "name:" not in body


def test_parse_accepts_crlf_and_bom() -> None:
    text = "\ufeff" + VALID_REGIMEN_TEXT.replace("\n", "\r\n")
    meta, body = parse_skill_md(text)
    assert meta["name"] == "regimen-test"
    assert "本文" in body


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# 見出しだけ\n本文\n",
        "name: regimen-test\n---\n本文\n",
        "---\nname: regimen-test\nversion: 1\n",  # 閉じていない
        "---\nname: [regimen-test\n---\n本文\n",  # YAML として壊れている
        "---\nname: regimen-test\n  version: : 1\n---\n",  # YAML として壊れている
        "---\n---\n本文\n",  # 空の frontmatter
        "---\n- a\n- b\n---\n本文\n",  # mapping でない
        "---\njust a string\n---\n本文\n",  # mapping でない
    ],
)
def test_parse_rejects_broken_frontmatter(text: str) -> None:
    with pytest.raises(SkillFormatError) as exc:
        parse_skill_md(text)
    assert exc.value.code == "format"


def test_format_error_is_a_validation_error() -> None:
    # 呼び出し側は SkillValidationError だけを捕まえれば足りる
    assert issubclass(SkillFormatError, SkillValidationError)


# ---------------------------------------------------------------------------
# validate_skill_text
# ---------------------------------------------------------------------------


def test_validate_valid_regimen_text() -> None:
    skill = validate_skill_text("regimen-test", VALID_REGIMEN_TEXT)
    assert isinstance(skill, RegimenSkill)
    assert skill.skill_version == "regimen-test@1"


def test_validate_report_format_text() -> None:
    text = (
        "---\nname: report-format-test\ndescription: テスト\nversion: 2\n"
        "sections: [header, grid]\n---\n本文\n"
    )
    skill = validate_skill_text("report-format-test", text)
    assert isinstance(skill, ReportFormatSkill)
    assert skill.sections == ["header", "grid"]
    assert skill.quotes_max_items == 30


def _assert_code(skill_name: str, text: str, code: str) -> None:
    with pytest.raises(SkillValidationError) as exc:
        validate_skill_text(skill_name, text)
    assert exc.value.code == code


def test_validate_rejects_broken_yaml() -> None:
    broken = _replace_line(VALID_REGIMEN_TEXT, "version: 1", "version: [1")
    _assert_code("regimen-test", broken, "format")


def test_validate_rejects_name_mismatch() -> None:
    _assert_code("regimen-other", VALID_REGIMEN_TEXT, "name_mismatch")


def test_validate_rejects_duplicate_question_keys() -> None:
    dup = _replace_line(
        VALID_REGIMEN_TEXT,
        "  - {key: fever, text: 熱を測りましたか, answer_type: temperature}",
        "  - {key: diarrhea, text: 熱を測りましたか, answer_type: temperature}\n"
        "  - {key: fever, text: 熱を測りましたか, answer_type: temperature}",
    )
    _assert_code("regimen-test", dup, "schema")


def test_validate_rejects_fixed_rule_with_unknown_question() -> None:
    bad = _replace_line(
        VALID_REGIMEN_TEXT, "question_key: fever,", "question_key: temperature,"
    )
    _assert_code("regimen-test", bad, "schema")


def test_validate_rejects_version_zero() -> None:
    bad = _replace_line(VALID_REGIMEN_TEXT, "version: 1", "version: 0")
    _assert_code("regimen-test", bad, "schema")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("version: 1", "version: 1\nunknown_field: x"),  # 未知の項目
        ("version: 1", 'version: "1"'),  # 文字列を数に直さない
        ("version: 1", "version: true"),
        ("cycle_days: 14", "cycle_days: 14.5"),
        ("regimen: FOLFOX", "regimen: folfox"),  # 識別名の書式（英大文字）
        ("cycle_days: 14", "cycle_days: 3"),
        ("answer_type: three_level", "answer_type: five_level"),
        ("{key: diarrhea,", "{key: Diarrhea,"),  # key の書式
        ("description: テスト用のレジメン\n", ""),  # description が無い
    ],
)
def test_validate_rejects_schema_violations(old: str, new: str) -> None:
    _assert_code("regimen-test", _replace_line(VALID_REGIMEN_TEXT, old, new), "schema")


def test_validate_rejects_empty_questions() -> None:
    text = (
        "---\nname: regimen-test\ndescription: テスト\nversion: 1\n"
        "regimen: FOLFOX\ncycle_days: 14\nquestions: []\n---\n本文\n"
    )
    _assert_code("regimen-test", text, "schema")


def test_validate_rejects_unknown_kind() -> None:
    text = VALID_REGIMEN_TEXT.replace("name: regimen-test", "name: other-test")
    _assert_code("other-test", text, "unknown_kind")


@pytest.mark.parametrize("name", ["regimen-Test", "regimen-", "regimen-a/b"])
def test_validate_rejects_invalid_names(name: str) -> None:
    _assert_code(name, VALID_REGIMEN_TEXT, "invalid_name")


def test_validate_rejects_too_large_text() -> None:
    huge = VALID_REGIMEN_TEXT + ("あ" * 200_000)
    _assert_code("regimen-test", huge, "too_large")


def test_validate_size_limit_boundary() -> None:
    exact = VALID_REGIMEN_TEXT + "あ" * (MAX_SKILL_CHARS - len(VALID_REGIMEN_TEXT))
    assert len(exact) == MAX_SKILL_CHARS
    assert isinstance(validate_skill_text("regimen-test", exact), RegimenSkill)
    _assert_code("regimen-test", exact + "あ", "too_large")


def test_validate_does_not_accept_non_string() -> None:
    with pytest.raises(SkillValidationError) as exc:
        validate_skill_text("regimen-test", None)  # type: ignore[arg-type]
    assert exc.value.code == "format"


# ---------------------------------------------------------------------------
# skill_path / 名前の検査（パストラバーサル防止）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../etc",
        "..",
        "",
        "regimen-../../etc",
        "regimen-folfox/../../etc",
        "regimen-folfox\n",
        "/etc/passwd",
        "regimen_folfox",
        "REGIMEN-FOLFOX",
        "skill-folfox",
        "regimen-ふぉるふぉっくす",
    ],
)
def test_skill_path_rejects_unsafe_names(name: str, tmp_path: Path) -> None:
    with pytest.raises(SkillValidationError) as exc:
        skill_path(name, skills_dir=tmp_path)
    assert exc.value.code == "invalid_name"
    assert not is_valid_skill_name(name)


def test_skill_path_stays_inside_skills_dir(tmp_path: Path) -> None:
    path = skill_path("report-format-dr-a", skills_dir=tmp_path)
    assert path == tmp_path / "report-format-dr-a" / "SKILL.md"
    assert path.resolve().is_relative_to(tmp_path.resolve())


def test_skill_name_pattern_matches_contract() -> None:
    assert SKILL_NAME_PATTERN == r"^(regimen|report-format)-[a-z0-9-]+$"
    for name in REAL_SKILLS:
        assert is_valid_skill_name(name)


# ---------------------------------------------------------------------------
# skills_dir を差し替えて読む
# ---------------------------------------------------------------------------


def test_load_from_tmp_skills_dir(tmp_path: Path) -> None:
    _write_skill(tmp_path, "regimen-test", VALID_REGIMEN_TEXT)
    assert read_skill_text("regimen-test", skills_dir=tmp_path) == VALID_REGIMEN_TEXT
    skill = load_skill("regimen-test", skills_dir=tmp_path)
    assert isinstance(skill, RegimenSkill)
    assert [q.key for q in skill.questions] == ["diarrhea", "fever"]


def test_load_regimen_skill_from_copied_dir(tmp_path: Path) -> None:
    for name in REAL_SKILLS:
        shutil.copytree(config.SKILLS_DIR / name, tmp_path / name)
    assert load_regimen_skill("FOLFOX", skills_dir=tmp_path).name == "regimen-folfox"
    assert load_regimen_skill("CAPOX", skills_dir=tmp_path).name == "regimen-capox"
    assert load_report_skill(skills_dir=tmp_path).name == "report-format-default"


def test_skills_dir_env_is_used_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_skill(tmp_path, "regimen-test", VALID_REGIMEN_TEXT)
    monkeypatch.setenv("TSUTAE_SKILLS_DIR", str(tmp_path))
    assert load_skill("regimen-test").name == "regimen-test"


def test_missing_skill_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(SkillValidationError) as exc:
        read_skill_text("regimen-folfox", skills_dir=tmp_path)
    assert exc.value.code == "not_found"


def test_broken_file_on_disk_is_rejected(tmp_path: Path) -> None:
    _write_skill(tmp_path, "regimen-test", "壊れた SKILL.md\n")
    with pytest.raises(SkillValidationError) as exc:
        load_skill("regimen-test", skills_dir=tmp_path)
    assert exc.value.code == "format"


def test_load_regimen_skill_rejects_unknown_regimen(tmp_path: Path) -> None:
    with pytest.raises(SkillValidationError) as exc:
        load_regimen_skill("XELOX", skills_dir=tmp_path)  # type: ignore[arg-type]
    assert exc.value.code == "unknown_regimen"


def test_load_regimen_skill_rejects_regimen_mismatch(tmp_path: Path) -> None:
    text = VALID_REGIMEN_TEXT.replace("name: regimen-test", "name: regimen-capox")
    _write_skill(tmp_path, "regimen-capox", text)  # 中身は regimen: FOLFOX
    with pytest.raises(SkillValidationError) as exc:
        load_regimen_skill("CAPOX", skills_dir=tmp_path)
    assert exc.value.code == "regimen_mismatch"


def test_load_report_skill_rejects_regimen_skill(tmp_path: Path) -> None:
    _write_skill(tmp_path, "regimen-test", VALID_REGIMEN_TEXT)
    with pytest.raises(SkillValidationError) as exc:
        load_report_skill("regimen-test", skills_dir=tmp_path)
    assert exc.value.code == "unknown_kind"


def test_validation_error_carries_code_and_message() -> None:
    err = SkillValidationError("schema", "questions の key が重複している")
    assert err.code == "schema"
    assert "schema" in str(err)


# ---------------------------------------------------------------------------
# 置き場所の外へ出るシンボリックリンク・読めないファイル
# ---------------------------------------------------------------------------


def _outside_skill(tmp_path: Path) -> tuple[Path, Path]:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    outside = tmp_path / "outside"
    _write_skill(outside, "regimen-evil", VALID_REGIMEN_TEXT)
    return skills_dir, outside / "regimen-evil"


def test_skill_path_rejects_symlinked_dir_outside(tmp_path: Path) -> None:
    skills_dir, outside_dir = _outside_skill(tmp_path)
    (skills_dir / "regimen-evil").symlink_to(outside_dir, target_is_directory=True)
    for call in (skill_path, read_skill_text, load_skill):
        with pytest.raises(SkillValidationError) as exc:
            call("regimen-evil", skills_dir=skills_dir)
        assert exc.value.code == "invalid_name"


def test_skill_path_rejects_symlinked_file_outside(tmp_path: Path) -> None:
    skills_dir, outside_dir = _outside_skill(tmp_path)
    (skills_dir / "regimen-evil").mkdir()
    (skills_dir / "regimen-evil" / "SKILL.md").symlink_to(outside_dir / "SKILL.md")
    for call in (skill_path, read_skill_text, load_skill):
        with pytest.raises(SkillValidationError) as exc:
            call("regimen-evil", skills_dir=skills_dir)
        assert exc.value.code == "invalid_name"


def test_non_utf8_file_is_format_error(tmp_path: Path) -> None:
    target = tmp_path / "regimen-test" / "SKILL.md"
    target.parent.mkdir()
    target.write_bytes(VALID_REGIMEN_TEXT.encode("shift_jis"))
    for call in (read_skill_text, load_skill):
        with pytest.raises(SkillValidationError) as exc:
            call("regimen-test", skills_dir=tmp_path)
        assert exc.value.code == "format"


# ---------------------------------------------------------------------------
# YAML の型変換の失敗・日付風の文字列・重複キー
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "new",
    [
        "version: !!int abc",
        "version: !!float abc",
        "version: !!timestamp 2026-02-30",
        "version: !!timestamp 2026-13-45",
        "version: " + "[" * 3000 + "]" * 3000,  # 深い入れ子（RecursionError）
        "version: 1\n[a, b]: x",  # ハッシュできないキー
        "version: !!map foo",  # mapping でないものに mapping のタグ
    ],
)
def test_validate_turns_yaml_construction_errors_into_format(new: str) -> None:
    text = _replace_line(VALID_REGIMEN_TEXT, "version: 1", new)
    assert len(text) <= MAX_SKILL_CHARS
    with pytest.raises(SkillFormatError) as exc:
        parse_skill_md(text)
    assert exc.value.code == "format"
    _assert_code("regimen-test", text, "format")


def test_date_like_values_stay_strings() -> None:
    meta, _ = parse_skill_md(
        "---\ndescription: 2026-02-30\ntext: 2026-13-45\n"
        "day: 2026-11-03\nat: 2026-11-03 10:00:00\n---\n本文\n"
    )
    assert meta == {
        "description": "2026-02-30",
        "text": "2026-13-45",
        "day": "2026-11-03",
        "at": "2026-11-03 10:00:00",
    }


def test_date_like_description_is_accepted_as_text() -> None:
    text = _replace_line(
        VALID_REGIMEN_TEXT, "description: テスト用のレジメン", "description: 2026-11-03"
    )
    skill = validate_skill_text("regimen-test", text)
    assert skill.description == "2026-11-03"


def test_global_safe_loader_is_untouched() -> None:
    # 子クラスだけを変え、yaml.SafeLoader（他のモジュールも使う）は変えない
    assert yaml.safe_load("d: 2026-11-03")["d"] == date(2026, 11, 3)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("version: 1", "version: 1\nversion: 7"),
        (
            "fixed_rules:",
            "questions:\n"
            "  - {key: fever, text: 熱を測りましたか, answer_type: temperature}\n"
            "fixed_rules:",
        ),
        ("{key: diarrhea, text:", "{key: diarrhea, key: stomatitis, text:"),
    ],
)
def test_validate_rejects_duplicate_yaml_keys(old: str, new: str) -> None:
    _assert_code("regimen-test", _replace_line(VALID_REGIMEN_TEXT, old, new), "format")


def test_real_folfox_with_second_questions_block_is_rejected() -> None:
    real = read_skill_text("regimen-folfox", skills_dir=config.SKILLS_DIR)
    added = _replace_line(
        real,
        "fixed_rules:",
        "questions:\n"
        "  - {key: fever, text: 熱を測りましたか, answer_type: temperature}\n"
        "fixed_rules:",
    )
    _assert_code("regimen-folfox", added, "format")


def test_yaml_merge_key_is_not_a_duplicate() -> None:
    meta, _ = parse_skill_md(
        "---\nbase: &b {a: 1, b: 2}\nx:\n  <<: *b\n  a: 3\n---\n本文\n"
    )
    assert meta["x"] == {"a": 3, "b": 2}


def test_reads_the_same_as_safe_load_apart_from_dates() -> None:
    source = "=: 1\n'1': a\n1: b\nno: c\nlist: [1, 2.5, null, ~, x]\n"
    meta, _ = parse_skill_md(f"---\n{source}---\n本文\n")
    assert meta == yaml.safe_load(source)


def test_duplicate_after_type_conversion_is_rejected() -> None:
    # yes と true はどちらも True（YAML 1.1）。後勝ちで片方が消えるので重複として止める
    with pytest.raises(SkillFormatError):
        parse_skill_md("---\nyes: a\ntrue: b\n---\n本文\n")
    with pytest.raises(SkillFormatError):  # 1 と True も Python の dict では同じキー
        parse_skill_md("---\n1: a\nyes: b\n---\n本文\n")


# ---------------------------------------------------------------------------
# 名前とレジメンの対応・ポンプ抜去日・固定規則（D4 の検査経路）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("regimen-folfox", "regimen: FOLFOX", "regimen: CAPOX"),
        ("regimen-capox", "regimen: CAPOX", "regimen: FOLFOX"),
    ],
)
def test_validate_rejects_regimen_that_does_not_match_skill_name(
    name: str, old: str, new: str
) -> None:
    real = read_skill_text(name, skills_dir=config.SKILLS_DIR)
    _assert_code(name, _replace_line(real, old, new), "regimen_mismatch")


@pytest.mark.parametrize("value", ["0", "-1", "15", "99"])
def test_validate_rejects_pump_removal_day_out_of_cycle(value: str) -> None:
    bad = _replace_line(
        VALID_REGIMEN_TEXT, "pump_removal_day: 3", f"pump_removal_day: {value}"
    )
    _assert_code("regimen-test", bad, "schema")


@pytest.mark.parametrize("value", ["1", "14", "null"])
def test_validate_accepts_pump_removal_day_within_cycle(value: str) -> None:
    ok = _replace_line(
        VALID_REGIMEN_TEXT, "pump_removal_day: 3", f"pump_removal_day: {value}"
    )
    skill = validate_skill_text("regimen-test", ok)
    assert isinstance(skill, RegimenSkill)
    assert skill.pump_removal_day == (None if value == "null" else int(value))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("threshold_celsius: 38.0", "threshold_celsius: .nan"),
        ("threshold_celsius: 38.0", "threshold_celsius: .inf"),
        ("threshold_celsius: 38.0", "threshold_celsius: -.inf"),
        ("threshold_celsius: 38.0", "threshold_celsius: -5.0"),
        ("threshold_celsius: 38.0", "threshold_celsius: 34.9"),
        ("threshold_celsius: 38.0", "threshold_celsius: 42.1"),
        ("question_key: fever,", "question_key: diarrhea,"),  # 体温の質問でない
        ("patient_string_key: fixed_rule.fever_38", "patient_string_key: no.such.key"),
    ],
)
def test_validate_rejects_fixed_rules_that_could_never_fire(old: str, new: str) -> None:
    _assert_code("regimen-test", _replace_line(VALID_REGIMEN_TEXT, old, new), "schema")


@pytest.mark.parametrize("value", ["35.0", "42.0", "38"])
def test_validate_accepts_threshold_within_range(value: str) -> None:
    ok = _replace_line(
        VALID_REGIMEN_TEXT, "threshold_celsius: 38.0", f"threshold_celsius: {value}"
    )
    skill = validate_skill_text("regimen-test", ok)
    assert isinstance(skill, RegimenSkill)
    assert skill.fixed_rules[0].threshold_celsius == float(value)


# ---------------------------------------------------------------------------
# report-format の schema 違反
# ---------------------------------------------------------------------------

VALID_REPORT_TEXT = (
    "---\nname: report-format-test\ndescription: テスト\nversion: 2\n"
    "sections: [header, grid]\n---\n本文\n"
)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("sections: [header, grid]", "sections: [header, footer]"),  # 未知の欄
        ("sections: [header, grid]", "sections: []"),
        ("sections: [header, grid]", "sections: header"),
        ("version: 2", "version: 0"),
        ("version: 2", "version: 2\nquotes_max_items: 201"),
        ("version: 2", "version: 2\nquotes_max_items: -1"),
        ("version: 2", "version: 2\nquotes_max_items: 3.5"),
        ("version: 2", "version: 2\nlow_confidence_threshold: 1.5"),
        ("version: 2", "version: 2\nlow_confidence_threshold: .nan"),
        ("version: 2", "version: 2\nfever_attention_celsius: 34.0"),
        ("version: 2", "version: 2\nshow_previous_course: 1"),
        ("version: 2", 'version: 2\nshow_temperature_row: "true"'),
        ("version: 2", "version: 2\nregimen: FOLFOX"),  # レジメンの項目は無い
        ("description: テスト\n", ""),
    ],
)
def test_validate_rejects_report_format_schema_violations(old: str, new: str) -> None:
    bad = _replace_line(VALID_REPORT_TEXT, old, new)
    _assert_code("report-format-test", bad, "schema")

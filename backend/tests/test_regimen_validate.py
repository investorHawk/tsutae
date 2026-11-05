"""フォームの値の検査（T91。spec 9.1「投与スケジュールの検査」「値の形の検査」）。"""

from __future__ import annotations

from typing import Any

import pytest
from regimen_fixtures import EXTRA_REGIMENS

from tsutae.regimen import (
    FieldIssue,
    RegimenForm,
    load_builtin_form,
    missing_fields,
    validate_complete_form,
    validate_form,
)


def _form(data: dict[str, Any]) -> RegimenForm:
    return RegimenForm.model_validate(data)


def _issues(data: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.field_id, i.code) for i in validate_complete_form(_form(data))}


def _ram() -> dict[str, Any]:
    return EXTRA_REGIMENS["ram_wptx"]()


def _lonsurf() -> dict[str, Any]:
    return EXTRA_REGIMENS["lonsurf_bv"]()


def _folfiri() -> dict[str, Any]:
    return EXTRA_REGIMENS["folfiri_bv"]()


@pytest.mark.parametrize("name", ["regimen-folfox", "regimen-capox"])
def test_builtin_forms_are_clean(name: str) -> None:
    assert validate_complete_form(load_builtin_form(name)) == []


@pytest.mark.parametrize("key", sorted(EXTRA_REGIMENS))
def test_extra_regimens_are_clean(key: str) -> None:
    assert validate_complete_form(_form(EXTRA_REGIMENS[key]())) == []


def test_issue_has_field_id_code_and_message() -> None:
    data = _ram()
    data["basic"]["cycle_days"] = 50
    [issue] = validate_form(_form(data))
    assert isinstance(issue, FieldIssue)
    assert issue.field_id == "basic.cycle_days"
    assert issue.code == "out_of_range"
    assert issue.message


# ---------------------------------------------------------------------------
# 基本
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code", ["ram-wptx", "1RAM", "RAM_WPTX", "RAM-", "-RAM", "R" * 31]
)
def test_bad_code_is_rejected(code: str) -> None:
    data = _ram()
    data["basic"]["code"] = code
    assert ("basic.code", "pattern") in _issues(data)


@pytest.mark.parametrize("days", [6, 43, 0])
def test_cycle_days_must_be_7_to_42(days: int) -> None:
    data = _ram()
    data["basic"]["cycle_days"] = days
    assert ("basic.cycle_days", "out_of_range") in _issues(data)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("RAM: wPTX", "yaml"),
        ("*RAM", "yaml"),
        ("RAM\nwPTX", "line_break"),
        ("RAM|wPTX", "pipe"),
        (" RAM", "whitespace"),
        ("R" * 41, "too_long"),
    ],
)
def test_display_name_must_round_trip(value: str, code: str) -> None:
    data = _ram()
    data["basic"]["display_name"] = value
    assert ("basic.display_name", code) in _issues(data)


# ---------------------------------------------------------------------------
# 投与スケジュール（spec 9.1）
# ---------------------------------------------------------------------------


def test_day1_needs_an_infusion() -> None:
    data = _lonsurf()
    data["drugs"][1]["days"] = [{"start": 15, "end": 15}]
    assert ("drugs", "day1_infusion") in _issues(data)


def test_oral_only_regimen_is_out_of_scope() -> None:
    data = _lonsurf()
    data["drugs"] = data["drugs"][:1]
    assert ("drugs", "day1_infusion") in _issues(data)


def test_only_one_pump() -> None:
    data = _folfiri()
    pump = dict(data["drugs"][4], row_id="d-pump2")
    data["drugs"].append(pump)
    assert ("drugs.d-pump2.route", "too_many_pumps") in _issues(data)


def test_pump_is_one_range_from_day1() -> None:
    data = _folfiri()
    data["drugs"][4]["days"] = [{"start": 2, "end": 3}]
    assert ("drugs.d-fu-pump.days", "pump_range") in _issues(data)
    data["drugs"][4]["days"] = [{"start": 1, "end": 2}, {"start": 4, "end": 5}]
    assert ("drugs.d-fu-pump.days", "pump_range") in _issues(data)


def test_only_one_oral() -> None:
    data = _lonsurf()
    data["drugs"].append(dict(data["drugs"][0], row_id="d-oral2"))
    assert ("drugs.d-oral2.route", "too_many_orals") in _issues(data)


def test_oral_needs_times_and_start_note() -> None:
    data = _lonsurf()
    data["drugs"][0]["times_per_day"] = None
    data["drugs"][0]["start_note"] = None
    missing = {(i.field_id, i.code) for i in missing_fields(_form(data))}
    assert ("drugs.d-ftd.times_per_day", "required") in missing
    assert ("drugs.d-ftd.start_note", "required") in missing


def test_times_per_day_is_only_for_oral() -> None:
    data = _ram()
    data["drugs"][0]["times_per_day"] = 2
    assert ("drugs.d-ptx.times_per_day", "not_oral") in _issues(data)


@pytest.mark.parametrize("times", [0, 5])
def test_times_per_day_range(times: int) -> None:
    data = _lonsurf()
    data["drugs"][0]["times_per_day"] = times
    assert ("drugs.d-ftd.times_per_day", "out_of_range") in _issues(data)


@pytest.mark.parametrize(
    "days",
    [
        [{"start": 1, "end": 5}, {"start": 5, "end": 12}],  # 重なる
        [{"start": 3, "end": 1}],  # 逆向き
        [{"start": 0, "end": 2}],
        [{"start": 20, "end": 29}],  # 1コースの外
        [],
    ],
)
def test_bad_day_ranges(days: list[dict[str, int]]) -> None:
    data = _lonsurf()
    data["drugs"][0]["days"] = days
    issues = validate_complete_form(_form(data))
    assert "drugs.d-ftd.days" in {i.field_id for i in issues}


def test_days_must_fit_after_cycle_change() -> None:
    data = _ram()
    data["basic"]["cycle_days"] = 14
    assert ("drugs.d-ptx.days", "out_of_range") in _issues(data)


def test_ranges_are_sorted_in_the_form() -> None:
    data = _lonsurf()
    data["drugs"][0]["days"] = [{"start": 8, "end": 12}, {"start": 1, "end": 5}]
    assert ("drugs.d-ftd.days", "order") in _issues(data)


# ---------------------------------------------------------------------------
# 薬の量・H1・値の形
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "パクリタキセル 80mg/m2",
        "パクリタキセル80ｍｇ",
        "5mg/kg",
        "1.5g",
        "100 mL",
        "AUC5",
        "2単位",
        "500μg",
    ],
)
def test_drug_dose_is_rejected(value: str) -> None:
    data = _ram()
    data["drugs"][0]["name"] = value
    assert ("drugs.d-ptx.name", "dose") in _issues(data)


@pytest.mark.parametrize(
    "value", ["フルオロウラシル（46時間）", "Day1 の朝から", "1日2回", "38.0℃"]
)
def test_non_dose_numbers_are_allowed(value: str) -> None:
    data = _lonsurf()
    data["drugs"][0]["start_note"] = value
    assert _issues(data) == set()


def test_dose_in_notes_is_rejected() -> None:
    data = _ram()
    data["notes"] = "パクリタキセルは 80mg/m2 で入れる"
    assert ("notes", "dose") in _issues(data)


@pytest.mark.parametrize(
    "value", ["電話 090-1234-5678 に連絡", "山田さんに聞く", "a@example.com"]
)
def test_identifier_is_rejected_without_echoing_text(value: str) -> None:
    data = _ram()
    data["notes"] = value
    issues = [i for i in validate_form(_form(data)) if i.field_id == "notes"]
    assert [i.code for i in issues] == ["identifier"]
    assert value not in issues[0].message


def test_identifier_in_phrase_is_rejected() -> None:
    data = _ram()
    data["side_effects"][0]["phrases"] = ["佐藤さんがしびれると言う"]
    assert ("side_effects.se-neuropathy.phrases", "identifier") in _issues(data)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("だるさは, ありましたか", "yaml"),
        ("だるさは{ありましたか}", "yaml"),
        ("だるさ: ありましたか", "yaml"),
        ("だるさ #ありましたか", "yaml"),
        ("だるさは\nありましたか", "line_break"),
        ("", "required"),
    ],
)
def test_question_text_must_round_trip(value: str, code: str) -> None:
    data = _ram()
    data["questions"][4]["text"] = value
    issues = {(i.field_id, i.code) for i in validate_complete_form(_form(data))}
    assert ("questions.q-fatigue.text", code) in issues


@pytest.mark.parametrize("value", ["しびれ|ピリピリ", "しびれ\nピリピリ"])
def test_table_cell_has_no_pipe_or_line_break(value: str) -> None:
    data = _ram()
    data["side_effects"][0]["phrases"] = [value]
    codes = {c for f, c in _issues(data) if f == "side_effects.se-neuropathy.phrases"}
    assert codes & {"pipe", "line_break"}


# ---------------------------------------------------------------------------
# 副作用と質問
# ---------------------------------------------------------------------------


def test_unknown_ctcae_term_is_rejected() -> None:
    data = _ram()
    data["side_effects"][0]["ctcae_terms"] = ["四肢浮腫"]
    assert ("side_effects.se-neuropathy.ctcae_terms", "unknown_term") in _issues(data)


def test_same_term_in_two_rows_is_rejected() -> None:
    data = _ram()
    data["side_effects"][1]["ctcae_terms"] = ["下痢", "疲労"]
    # 後に出た行（だるさの行）を咎める
    assert ("side_effects.se-fatigue.ctcae_terms", "duplicate_term") in _issues(data)


def test_side_effect_question_must_exist() -> None:
    data = _ram()
    data["side_effects"][0]["question_key"] = "numbness"
    assert ("side_effects.se-neuropathy.question_key", "unknown_question") in _issues(
        data
    )


def test_question_keys_are_unique() -> None:
    data = _ram()
    data["questions"][1]["key"] = "neuropathy"
    assert ("questions.q-diarrhea.key", "duplicate") in _issues(data)


@pytest.mark.parametrize("key", ["Fatigue", "f", "1fatigue", "fa-tigue"])
def test_question_key_pattern(key: str) -> None:
    data = _ram()
    data["questions"][4]["key"] = key
    assert ("questions.q-fatigue.key", "pattern") in _issues(data)


def test_temperature_question_is_required() -> None:
    data = _ram()
    data["questions"] = [q for q in data["questions"] if q["key"] != "fever"]
    data["side_effects"] = [
        s for s in data["side_effects"] if s["question_key"] != "fever"
    ]
    assert ("questions", "temperature_required") in _issues(data)


def test_only_one_temperature_question() -> None:
    data = _ram()
    data["questions"].append(
        {
            "row_id": "q-temp2",
            "key": "temp2",
            "label": "体温2",
            "text": "体温は測りましたか",
            "answer_type": "temperature",
        }
    )
    assert ("questions.q-temp2.answer_type", "too_many_temperature") in _issues(data)


def test_duplicate_row_ids_are_rejected() -> None:
    data = _ram()
    data["drugs"][1]["row_id"] = "d-ptx"
    assert ("drugs.d-ptx", "duplicate_row") in _issues(data)


@pytest.mark.parametrize("row_id", ["", "D-1", "a.b", "x" * 33])
def test_bad_row_id(row_id: str) -> None:
    data = _ram()
    data["drugs"][0]["row_id"] = row_id
    assert any(c == "row_id" for _f, c in _issues(data))


# ---------------------------------------------------------------------------
# 必須（下書きの途中は validate_form では咎めない）
# ---------------------------------------------------------------------------


def test_partial_draft_passes_value_checks() -> None:
    draft = RegimenForm.model_validate(
        {
            "basic": {},
            "questions": [
                {
                    "row_id": "q-fever",
                    "key": "fever",
                    "label": "体温",
                    "text": "熱を測りましたか",
                    "answer_type": "temperature",
                }
            ],
        }
    )
    assert validate_form(draft) == []
    missing = {(i.field_id, i.code) for i in missing_fields(draft)}
    assert {
        ("basic.display_name", "required"),
        ("basic.code", "required"),
        ("basic.cycle_days", "required"),
        ("drugs", "required"),
        ("side_effects", "required"),
    } <= missing
    assert ("basic.target", "required") not in missing


def test_partial_drug_row_is_reported_as_missing() -> None:
    data = _ram()
    data["drugs"].append({"row_id": "d-new"})
    assert validate_form(_form(data)) == []
    missing = {(i.field_id, i.code) for i in missing_fields(_form(data))}
    assert {
        ("drugs.d-new.name", "required"),
        ("drugs.d-new.route", "required"),
        ("drugs.d-new.days", "required"),
    } <= missing


# ---------------------------------------------------------------------------
# 検証者の指摘（frontmatter に入る識別名・key の読み戻し、H1、文字の種類）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["NO", "NULL", "OFF", "YES", "ON", "TRUE", "FALSE"])
def test_code_must_round_trip_as_yaml(code: str) -> None:
    """YAML 1.1 の真偽・null に読める識別名は `regimen:` に入れると文字列に戻らない。"""
    data = _ram()
    data["basic"]["code"] = code
    assert ("basic.code", "yaml") in _issues(data)


@pytest.mark.parametrize("key", ["no", "null", "on", "off", "yes", "true", "false"])
def test_question_key_must_round_trip_as_yaml(key: str) -> None:
    data = _ram()
    data["questions"][4]["key"] = key
    data["side_effects"][4]["question_key"] = key
    assert ("questions.q-fatigue.key", "yaml") in _issues(data)


def test_realistic_codes_and_keys_are_allowed() -> None:
    for code in ["S-1", "TAS-102", "SOX", "XELOX", "GEM-NABPTX", "NOX"]:
        data = _ram()
        data["basic"]["code"] = code
        assert _issues(data) == set(), code
    for key in ["fatigue2", "pain_2", "tired_feeling", "nothing"]:
        data = _ram()
        data["questions"][4]["key"] = key
        data["side_effects"][4]["question_key"] = key
        assert _issues(data) == set(), key


def test_identifier_in_code_is_rejected() -> None:
    data = _ram()
    data["basic"]["code"] = "A-09012345678"
    issues = [i for i in validate_form(_form(data)) if i.field_id == "basic.code"]
    assert [i.code for i in issues] == ["identifier"]
    assert "09012345678" not in issues[0].message


def test_identifier_in_question_key_is_rejected() -> None:
    data = _ram()
    data["questions"][4]["key"] = "item_12345678"
    data["side_effects"][4]["question_key"] = "item_12345678"
    assert ("questions.q-fatigue.key", "identifier") in _issues(data)


@pytest.mark.parametrize(
    "days",
    [
        [{"start": 1, "end": 5}, {"start": 6, "end": 10}],
        [{"start": 1, "end": 1}, {"start": 2, "end": 2}],
    ],
)
def test_adjacent_day_ranges_are_rejected(days: list[dict[str, int]]) -> None:
    """隣り合う範囲は1つにつなげる（休薬の行が内服の日を指さないように）。"""
    data = _lonsurf()
    data["drugs"][0]["days"] = days
    assert ("drugs.d-ftd.days", "adjacent") in _issues(data)


@pytest.mark.parametrize("char", ["​", "‍", "‎", " ", " ", "﻿", "\x07"])
@pytest.mark.parametrize(
    ("path", "field_id"),
    [
        (("basic", "display_name"), "basic.display_name"),
        (("questions", 4, "text"), "questions.q-fatigue.text"),
        (("questions", 4, "label"), "questions.q-fatigue.label"),
        (("drugs", 0, "name"), "drugs.d-ptx.name"),
    ],
)
def test_invisible_and_separator_chars_are_rejected(
    char: str, path: tuple[Any, ...], field_id: str
) -> None:
    data = _ram()
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = f"だる{char}さ"
    assert (field_id, "control") in _issues(data)


@pytest.mark.parametrize("char", [" ", "​", "﻿"])
def test_invisible_chars_in_phrases_and_notes_are_rejected(char: str) -> None:
    data = _ram()
    data["side_effects"][0]["phrases"] = [f"しび{char}れ"]
    data["notes"] = f"1行目{char}\n2行目"
    issues = _issues(data)
    assert ("side_effects.se-neuropathy.phrases", "control") in issues
    assert ("notes", "control") in issues


def test_tab_is_allowed_only_in_notes() -> None:
    data = _ram()
    data["notes"] = "施設の決まり\n\t字下げした行"
    assert _issues(data) == set()
    data["side_effects"][0]["phrases"] = ["しび\tれ"]
    assert ("side_effects.se-neuropathy.phrases", "control") in _issues(data)


@pytest.mark.parametrize("value", ["1行目\r\n2行目", "1行目\r2行目"])
def test_carriage_return_in_notes_is_rejected(value: str) -> None:
    """改行は LF だけ（画面の textarea の値は LF。CR は SKILL.md に残さない）。"""
    data = _ram()
    data["notes"] = value
    assert ("notes", "control") in _issues(data)


def test_duplicate_phrase_in_a_row_is_rejected() -> None:
    data = _ram()
    data["side_effects"][1]["phrases"] = ["下痢", "下痢"]
    assert ("side_effects.se-diarrhea.phrases", "duplicate_phrase") in _issues(data)

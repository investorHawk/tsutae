"""architecture.md §5「W2b の決定（2026-11-03）」の回帰テスト。

- normalize_text（check_text が最初に掛ける。改行は残す）
- 一次の仮名ID →「[ID]」
- 二次の address_number（番地・N-N-N）と id_like
- detect_identifiers（依頼文全体用。JSON のエスケープを空白とみなす）と
  detect_in_patient_text（患者の文用。例外なし）
- 改行・空白をまたぐ規則は、空白の前が名前の候補になる語のときだけ働く
- 合成データ3人で二次に掛かるのは demo の seq 38 と、識別子を足した記録だけ

人名・病院名・番号・住所は全て架空。
"""

from __future__ import annotations

import json
import time

import pytest

from tsutae.config import SYNTHETIC_DIR
from tsutae.masking import (
    ID_MASK,
    RULE_ADDRESS_NUMBER,
    RULE_AT_MARK,
    RULE_BEFORE_FACILITY,
    RULE_ID_LIKE,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    RULES,
    check_text,
    detect_identifiers,
    detect_in_patient_text,
    mask_text,
    normalize_text,
)
from tsutae.schemas import SyntheticPatient

DATASETS = ("demo_patient", "eval_patient_a", "eval_patient_b")


def _rules(text: str) -> list[str]:
    return [d.rule for d in check_text(text).detections]


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("下痢\r\n熱", "下痢\n熱"),
        ("下痢\r熱", "下痢\n熱"),
        ("下痢 熱 だるい", "下痢\n熱\nだるい"),
        ("下痢\tだるい", "下痢 だるい"),
        ("下痢\nだるい", "下痢\nだるい"),
        ("熱\x07センター", "熱センター"),
        ("磯​鷲さん", "磯鷲さん"),
        ("磯­鷲﻿さん⁠", "磯鷲さん"),
        ("\x00\x1f\x7f", ""),
        ("37.9℃", "37.9℃"),
        ("", ""),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_normalize_text_rejects_non_str() -> None:
    with pytest.raises(TypeError):
        normalize_text(None)  # type: ignore[arg-type]


def test_check_text_normalizes_first_and_keeps_line_breaks() -> None:
    check = check_text("下痢\r\n鈴木さん\tに相談\x07")
    assert check.masked == "下痢\n○○さん に相談"


def test_format_characters_do_not_hide_a_name() -> None:
    # ゼロ幅空白で姓を割っても、正規化の後に二次が拾う
    assert _rules("磯​鷲さんに相談") == [RULE_UNKNOWN_BEFORE_HONORIFIC]
    assert check_text("鈴​木さん").masked == "○○さん"


def test_detection_offsets_refer_to_the_normalized_text() -> None:
    check = check_text("\x07\x07磯鷲さん")
    d = check.detections[0]
    assert check.masked[d.start : d.end] == "磯鷲さん"


# ---------------------------------------------------------------------------
# 一次: 仮名ID →「[ID]」
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "P-DEMO0001",
        "p-demo0001",
        "Ｐ－ＤＥＭＯ０００１",
        "ｐ－ｄｅｍｏ０００１",
        "P‐AB12CD34",
        "P−AB12CD34",
    ],
)
def test_pseudonymous_id_is_replaced(text: str) -> None:
    result = mask_text(f"番号は{text}です")
    assert result.masked == f"番号は{ID_MASK}です"
    assert result.counts["id"] == 1


@pytest.mark.parametrize("text", ["P-DEMO001", "XP-DEMO0001", "P-DEMO00012"])
def test_id_like_text_that_is_not_exactly_an_id_is_left_for_secondary(
    text: str,
) -> None:
    result = mask_text(text)
    assert result.counts["id"] == 0
    assert check_text(text).flagged is True


def test_id_placeholder_is_not_detected() -> None:
    assert check_text("P-DEMO0001 で登録").masked == f"{ID_MASK} で登録"
    assert check_text("P-DEMO0001 で登録").flagged is False


# ---------------------------------------------------------------------------
# 二次: id_like
# ---------------------------------------------------------------------------


def test_id_like_rule_is_listed_last() -> None:
    assert RULES[-1] == RULE_ID_LIKE
    assert RULE_ADDRESS_NUMBER in RULES


@pytest.mark.parametrize(
    "text",
    [
        "受付はA-023でした",
        "A-023",
        "Ａ－０２３",
        "AB-1234",
        "受付 a-023",
        "P-DEMO0001X",
        "Aー023",
    ],
)
def test_id_like_is_detected(text: str) -> None:
    assert RULE_ID_LIKE in _rules(text)


@pytest.mark.parametrize(
    "text",
    [
        "PD-L1",
        "S-1を飲んだ",
        "HER-2",
        "5-FU",
        "CA19-9",
        "regimen-folfox",
        "report-format-default",
        "date-normalizer",
        "A-02",
        "UTF-8",
    ],
)
def test_short_or_long_prefix_is_not_id_like(text: str) -> None:
    assert RULE_ID_LIKE not in [d.rule for d in detect_in_patient_text(text)]


# ---------------------------------------------------------------------------
# 二次: address_number（番地・N-N-N）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["架空台2-3-4に住んでいる", "架空台 2-3-4", "架空台3番地", "架空台2丁目5番"],
)
def test_street_number_without_city_is_detected(text: str) -> None:
    assert RULE_ADDRESS_NUMBER in _rules(text)


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-03に点滴",
        "２０２６－１１－０３",
        "1-2錠",
        "毎日市販薬1-2錠",
        "37.9-38.2℃",
        "3番目の薬",
        "1番つらい",
    ],
)
def test_dates_and_doses_are_not_street_numbers(text: str) -> None:
    assert RULE_ADDRESS_NUMBER not in _rules(text)


def test_overlapping_street_number_matches_are_reported_once() -> None:
    found = detect_in_patient_text("架空町2丁目")
    assert [(d.rule, d.start, d.end) for d in found] == [(RULE_ADDRESS_NUMBER, 0, 6)]


@pytest.mark.parametrize("unit", ["1-2-3 ", "A-023 ", "3丁目", "\\n"])
def test_new_rules_are_fast_on_long_prompts(unit: str) -> None:
    prompt = json.dumps(unit * (60000 // len(unit)), ensure_ascii=False)
    started = time.perf_counter()
    detect_identifiers(prompt)
    assert time.perf_counter() - started < 1.0


# ---------------------------------------------------------------------------
# detect_identifiers（依頼文全体）と detect_in_patient_text（患者の文）
# ---------------------------------------------------------------------------


def _as_json(text: str) -> str:
    return json.dumps({"masked_free_text": text}, ensure_ascii=False)


@pytest.mark.parametrize(
    "text",
    [
        "だるい\n医院へ",
        "下痢\nセンターで相談",
        "下痢\t病院",
        "下痢\r\nクリニックで相談",
        '母は"病院"へ',
        "熱\\病院",
        "下痢\u0007センター",
        "37.9℃\n熱",
    ],
)
def test_json_escapes_are_read_as_blanks_in_the_prompt(text: str) -> None:
    assert detect_identifiers(_as_json(text)) == []


def test_json_escapes_keep_positions() -> None:
    prompt = _as_json("下痢\n磯鷲さん")
    found = detect_identifiers(prompt)
    assert [d.rule for d in found] == [RULE_UNKNOWN_BEFORE_HONORIFIC]
    assert prompt[found[0].start : found[0].end] == "磯鷲さん"


def test_escaped_name_across_line_break_is_still_detected_in_the_prompt() -> None:
    assert [d.rule for d in detect_identifiers(_as_json("担当者\nさんに聞いた"))] == [
        RULE_UNKNOWN_BEFORE_HONORIFIC
    ]


@pytest.mark.parametrize(
    "prompt",
    [
        '{"regimen_skill_version": "regimen-folfox@1"}',
        '{"report_skill_version":"report-format-default@2"}',
        '{"entries": [{"skill_version": "regimen-capox@1"}]}',
    ],
)
def test_skill_version_fields_are_the_only_at_mark_exception(prompt: str) -> None:
    assert detect_identifiers(prompt) == []
    assert RULE_AT_MARK in [d.rule for d in detect_in_patient_text(prompt)]


@pytest.mark.parametrize(
    "text",
    [
        '"regimen_skill_version": "regimen-folfox@1"',
        '\\"skill_version\\": \\"regimen-folfox@1\\"',
        "regimen-folfox@1",
        "連絡はaaa@1",
    ],
)
def test_patient_text_cannot_forge_the_skill_version_field(text: str) -> None:
    # 患者の文は JSON の中で " が \" になり、空白とみなされるのでキーの形にならない
    assert RULE_AT_MARK in [d.rule for d in detect_identifiers(_as_json(text))]
    assert RULE_AT_MARK in _rules(text)


def test_escaped_backslash_before_closing_quote_is_read_correctly() -> None:
    # 文の末尾の \ は \\ になり、その後ろの " は本物の閉じ引用符
    prompt = '{"a": "x\\\\", "skill_version": "regimen-folfox@1"}'
    assert detect_identifiers(prompt) == []


def test_unicode_escape_digits_are_not_counted() -> None:
    assert detect_identifiers(json.dumps("下痢と熱")) == []


# ---------------------------------------------------------------------------
# 改行・空白をまたぐ規則（空白の前が名前の候補になる語のときだけ）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "だるい\n医院へ",
        "つらい\n病院に電話",
        "きつかった\nクリニック",
        "しんどい\n病院",
        "はやく\n病院へ",
        "やっと\n病院",
        "ようやく\nクリニック",
        "熱\x07センターで相談",
        "熱センターで相談",
        "熱\nセンター",
        "咳\n病院",
        "つらい\n先生に相談",
        "だるい\n看護師さんに言った",
    ],
)
def test_adjective_or_adverb_before_line_break_is_not_detected(text: str) -> None:
    # 例外は改行の後だけ・明示の許可語（とその活用）だけ。通常の空白の場合と、
    # 語尾だけでは許さないことは test_masking_review3.py
    assert check_text(text).flagged is False


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("架空 病院", RULE_BEFORE_FACILITY),
        ("架空\n病院", RULE_BEFORE_FACILITY),
        ("かくう 病院", RULE_BEFORE_FACILITY),
        ("かくう\nクリニック", RULE_BEFORE_FACILITY),
        ("磯鷲\n南さん", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("担当者\nさんに聞いた", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("磯鷲\nさん", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("さとう\nさん", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("あおい\nちゃん", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("架空\u00a0病院", RULE_BEFORE_FACILITY),
        ("みらい 病院へ行った", RULE_BEFORE_FACILITY),
        ("みらい\n病院へ行った", RULE_BEFORE_FACILITY),
        ("みらい ちゃんに聞いた", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("磯鷲\u00a0南さん", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("磯鷲\u3000\n南さん", RULE_UNKNOWN_BEFORE_HONORIFIC),
    ],
)
def test_name_before_line_break_is_still_detected(text: str, rule: str) -> None:
    assert rule in _rules(text)


# ---------------------------------------------------------------------------
# 低の誤検知（レビュー指摘 8）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["くすりやさん", "やくざいしさん", "3日目さん", "はやく病院へ"]
)
def test_common_words_before_honorific_or_facility_are_not_detected(
    text: str,
) -> None:
    assert check_text(text).flagged is False


# ---------------------------------------------------------------------------
# 合成データ3人
# ---------------------------------------------------------------------------


def _patients() -> list[tuple[str, SyntheticPatient]]:
    found = []
    for name in DATASETS:
        path = SYNTHETIC_DIR / f"{name}.json"
        if not path.exists():
            pytest.skip(f"{name} の合成データがまだ無い")
        data = json.loads(path.read_text(encoding="utf-8"))
        found.append((name, SyntheticPatient.model_validate(data)))
    return found


def _free_texts() -> list[tuple[str, int, str]]:
    return [
        (name, e.seq, e.free_text)
        for name, patient in _patients()
        for e in patient.entries
        if e.free_text
    ]


def test_only_demo_seq_38_is_flagged_among_all_synthetic_records() -> None:
    flagged = [(n, s) for n, s, t in _free_texts() if check_text(t).flagged]
    assert flagged == [("demo_patient", 38)]


def test_masked_synthetic_texts_pass_the_whole_prompt_check() -> None:
    # 依頼文の JSON に埋め込んだ形（改行は \n の2字）でも誤検知しない
    leaks = [
        (n, s)
        for n, s, t in _free_texts()
        if not check_text(t).flagged
        and detect_identifiers(_as_json(check_text(t).masked))
    ]
    assert leaks == []


_INJECTED = (
    "磯鷲さん",
    "受付はA-023",
    "P-DEMO0001",
    "電話090\n1234\n5678",
    "架空台2-3-4",
    "架空\n病院",
    "isowashi@example.invalid",
    # レビュー3回目: 区切りの空白・改行が長い・ハイフンの前後に空白がある形
    "受付は A - 023",
    "受付は A -\n023",
    "P - DEMO0001",
    "P-\nDEMO0001",
    "電話090    1234    5678",
    "電話090\n\n\n\n1234\n\n\n\n5678",
    "電話090 \n 1234\n \n5678",
    "架空町   1-2",
    "架空町 1 - 2",
    "架空台1234-5-6",
    "みらい 病院",
    "みらい\n病院",
    "みらい ちゃん",
)


@pytest.mark.parametrize("identifier", _INJECTED)
def test_synthetic_records_with_an_identifier_are_caught(identifier: str) -> None:
    missed = []
    for name, seq, text in _free_texts():
        for combined in (f"{text}\n{identifier}", f"{identifier} {text}"):
            check = check_text(combined)
            if not check.flagged and identifier in check.masked:
                missed.append((name, seq))
            # 二次だけでも（一次が漏らしたときも）、依頼文の JSON の形で拾う
            raw = normalize_text(combined)
            if not detect_identifiers(_as_json(raw)):
                missed.append((name, seq))
    assert missed == []

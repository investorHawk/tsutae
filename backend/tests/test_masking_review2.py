"""W2 独立レビュー（Claude・Codex の2系統）の指摘に対する回帰テスト。

漏れの指摘は全て check_text（一次→二次）を通し、識別子が消えたか flagged になる
ことを確かめる（部品の関数だけでは確かめない）。誤検知が増えていないことも見る。
人名・病院名・番号・住所は全て架空。
"""

from __future__ import annotations

import dataclasses
import time

import pytest

from tsutae.masking import (
    RULE_ADDRESS_NUMBER,
    RULE_AT_MARK,
    RULE_BEFORE_FACILITY,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    RULES,
    check_text,
    detect_identifiers,
    mask_text,
)


def _is_caught(text: str, identifier: str) -> bool:
    """一次で伏せられた（識別子が残らない）か、二次に掛かったか。"""
    check = check_text(text)
    return identifier not in check.masked or check.flagged


def _rules(text: str) -> list[str]:
    return [d.rule for d in check_text(text).detections]


# ---------------------------------------------------------------------------
# 1, 9: 漢字＋ひらがな＋施設語の施設名
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "identifier"),
    [
        ("架空県立がんセンターで点滴", "架空"),
        ("架空こども病院へ行った", "架空"),
        ("架空みなと病院", "架空"),
        ("架空あおい病院", "架空"),
        ("架空さくらクリニック", "架空"),
        ("東さくら病院", "東"),
        ("架空がんセンター", "架空"),
        ("国立がんセンター", "国立"),
        ("国立がん医療センター", "国立"),
        ("カクウさくら病院", "カクウ"),
        ("大きなさくら病院", "さくら"),
    ],
)
def test_kanji_then_hiragana_facility_is_caught(text: str, identifier: str) -> None:
    assert _is_caught(text, identifier)


@pytest.mark.parametrize("text", ["架空さくらクリニック", "東さくら病院"])
def test_primary_masks_kanji_and_hiragana_together(text: str) -> None:
    assert mask_text(text).masked == "[病院]"


@pytest.mark.parametrize("text", ["架空[病院]", "東[病院]へ", "カクウ[病院]"])
def test_kanji_left_before_placeholder_is_detected(text: str) -> None:
    assert RULE_BEFORE_FACILITY in [d.rule for d in detect_identifiers(text)]


@pytest.mark.parametrize(
    "text",
    [
        "大きな病院",
        "新しい病院",
        "小さな病院",
        "大きい病院",
        "遠い病院",
        "同じ病院",
        "近くの病院",
        "今日病院へ",
        "母と病院へ",
        "昨日行った病院",
        "前に行った病院で",
        "入院した病院",
        "通っている病院",
        "通ってる病院",
        "紹介された病院",
        "具合が悪くなり病院へ",
        "仕方なく病院へ",
        "急いで病院へ",
        "熱が出たので病院",
        "今朝病院に電話した",
        "がんセンター",
        "保健センター",
        "今日[病院]へ",
        "朝[病院]へ",
        "紹介してもらった病院",
        "痛みで病院へ",
        "地域のがん診療センター",
    ],
)
def test_okurigana_and_time_words_before_facility_are_not_detected(
    text: str,
) -> None:
    assert check_text(text).flagged is False


# ---------------------------------------------------------------------------
# 2: 辞書にない1字の姓＋職種＋さん
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "島看護師さんに相談",
        "松薬剤師さん",
        "西看護師さん",
        "星薬剤師さん",
        "宮看護師さん",
        "鷲看護師さん",
    ],
)
def test_unknown_one_char_surname_before_role_is_detected(text: str) -> None:
    assert _rules(text) == [RULE_UNKNOWN_BEFORE_HONORIFIC]


@pytest.mark.parametrize(
    "text",
    ["新看護師さん", "前看護師さん", "元看護師さん", "男看護師さん", "女薬剤師さん"],
)
def test_allowed_one_char_prefix_before_role_is_not_detected(text: str) -> None:
    assert check_text(text).flagged is False


# ---------------------------------------------------------------------------
# 3: 空白で区切ったフルネームで、名が1字の姓と同じ字
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["磯鷲 南さん", "磯鷲　泉さん", "磯鷲\n南さん", "磯鷲 東先生", "カクウ 南さん"],
)
def test_full_name_with_space_and_one_char_given_name_is_caught(text: str) -> None:
    assert _rules(text) == [RULE_UNKNOWN_BEFORE_HONORIFIC]
    assert _is_caught(text, text[:2])


@pytest.mark.parametrize("text", ["今日 南さんに会った", "母と 南さん", "。 南さん"])
def test_allowed_word_before_space_and_surname_is_not_detected(text: str) -> None:
    assert check_text(text).flagged is False


# ---------------------------------------------------------------------------
# 4: 施設語の前の空白・改行
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["架空 病院", "架空　クリニック", "架空\n病院", "かくう 病院", "架空 [病院]"],
)
def test_name_separated_from_facility_by_space_is_detected(text: str) -> None:
    assert _rules(text) == [RULE_BEFORE_FACILITY]


@pytest.mark.parametrize(
    "text",
    ["今日 病院へ", "近所の 病院", "熱が出た。 病院に電話", "母と 病院へ", "朝 病院へ"],
)
def test_common_words_before_space_and_facility_are_not_detected(text: str) -> None:
    assert check_text(text).flagged is False


# ---------------------------------------------------------------------------
# 5, 7: 電話番号の区切り（読点・カンマ・改行・タブ・NBSP）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "090、1234、5678",
        "090,1234,5678",
        "０９０、１２３４、５６７８",
        "090，1234，5678",
        "090\n1234\n5678",
        "090\t1234\t5678",
        "090 1234 5678",
        "090\r\n1234\r\n5678",
        "電話は090\n1234\n5678です",
        "090    1234    5678",
        "090\n\n\n\n1234\n\n\n\n5678",
        "090 \n 1234\n \n5678",
    ],
)
def test_phone_with_comma_or_whitespace_separators_is_caught(text: str) -> None:
    check = check_text(text)
    assert "5678" not in check.masked or check.flagged


@pytest.mark.parametrize(
    "text", ["090\n1234\n5678", "090\t1234\t5678", "090 1234 5678"]
)
def test_primary_masks_phone_with_whitespace_separators(text: str) -> None:
    assert mask_text(text).masked == "[伏せ字]"


@pytest.mark.parametrize("text", ["1234\n5678", "123、4567", "12,345,678", "1234 5678"])
def test_secondary_counts_digits_across_new_separators(text: str) -> None:
    assert [d.rule for d in detect_identifiers(text)] == [RULE_LONG_DIGITS]


@pytest.mark.parametrize(
    "text", ["1、2、3日目", "3,000円", "体温37.5、脈88", "2026/11/03 10:00\n37.5"]
)
def test_short_numbers_with_commas_are_not_detected(text: str) -> None:
    assert check_text(text).flagged is False


def test_kanji_numeral_phone_is_detected() -> None:
    assert _rules("電話は九〇一二三四五六七八") == [RULE_LONG_DIGITS]


# ---------------------------------------------------------------------------
# 6: Skill 版の形の @ も検出する
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "LINEはregimen-folfox@1",
        "連絡は regimen-folfox@1",
        "regimen-folfox@1",
        "report-format-default@2",
    ],
)
def test_skill_version_like_at_mark_is_detected(text: str) -> None:
    check = check_text(text)
    assert check.flagged is True
    assert RULE_AT_MARK in [d.rule for d in check.detections]


# ---------------------------------------------------------------------------
# 8: 住所の区切りの空白・改行、二次の住所の規則
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "東京都千代田区架空町 1-2-3",
        "東京都 千代田区 架空町1-2-3",
        "東京都千代田区架空町\n1-2-3",
        "架空市架空町　2丁目3番",
        "神奈川県架空市 1-2",
    ],
)
def test_address_with_whitespace_is_masked(text: str) -> None:
    masked = mask_text(text).masked
    assert "架空町" not in masked and "1-2" not in masked
    assert "[伏せ字]" in masked


@pytest.mark.parametrize(
    "text",
    [
        "架空町 1-2-3",
        "架空市 1-2",
        "東京都 1-2",
        "架空村\n3番地",
        "架空区　4丁目",
    ],
)
def test_secondary_detects_place_followed_by_street_number(text: str) -> None:
    assert RULE_ADDRESS_NUMBER in [d.rule for d in detect_identifiers(text)]


@pytest.mark.parametrize(
    "text",
    [
        "東京へ行った",
        "東京都に住む娘",
        "市販薬1-2錠",
        "夜中に3-4回",
        "町内会に1回",
        "[伏せ字]",
        "1日2回",
    ],
)
def test_place_words_without_street_number_are_not_detected(text: str) -> None:
    assert check_text(text).flagged is False


def test_address_rule_is_listed() -> None:
    assert RULE_ADDRESS_NUMBER in RULES


# ---------------------------------------------------------------------------
# 11: 入れ子の書き換えもできない
# ---------------------------------------------------------------------------


def test_mask_check_detections_cannot_be_mutated() -> None:
    check = check_text("連絡は＠のあとに")
    assert isinstance(check.detections, tuple)
    with pytest.raises(AttributeError):
        check.detections.clear()  # type: ignore[attr-defined]
    assert check.flagged is True


def test_mask_check_counts_cannot_be_mutated() -> None:
    check = check_text("田中さんと話した")
    with pytest.raises(TypeError):
        check.counts["name"] = 0  # type: ignore[index]
    assert check.counts["name"] == 1


def test_mask_result_counts_cannot_be_mutated() -> None:
    result = mask_text("田中さんと話した")
    with pytest.raises(TypeError):
        result.counts["name"] = 0  # type: ignore[index]
    assert result.counts["name"] == 1


def test_mask_check_attributes_cannot_be_reassigned() -> None:
    check = check_text("田中さん")
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.masked = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# low: メールの正規表現が長い入力で2乗にならない
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["1-", "0-", "1.", "12."])
def test_mask_text_is_fast_on_long_dot_and_hyphen_runs(unit: str) -> None:
    text = unit * 30000
    started = time.perf_counter()
    mask_text(text)
    assert time.perf_counter() - started < 1.0

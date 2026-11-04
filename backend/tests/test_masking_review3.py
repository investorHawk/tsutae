"""レビュー3回目（2026-11-04）の回帰テスト。

1. 仮名ID・受付番号のハイフン前後の空白・改行（P - DEMO0001・A -\\n023）
2. 電話番号の区切りの字数（空白4字・改行4つ・空白と改行の混在）
3. 住所の構成要素間の空白（架空町   1-2・架空町 1 - 2）と、年でない4桁で始まる
   単位の無い N-N-N（架空台1234-5-6）
4. 空白・改行の前の語の例外は、改行のときだけ・明示の許可語（と、その活用）だけ
   （みらい 病院・みらい\\n病院・みらい ちゃん は検出する）

どの漏れも「患者の文（check_text）」と「依頼文の JSON に埋めた形（detect_identifiers）」
の両方で確かめる。一次が伏せた場合は伏せ字後の文に識別子が残らないこと、二次だけで
見た場合（一次が漏らしたとき）も原文を拾うことを確かめる。人名・番号・住所は全て架空。
"""

from __future__ import annotations

import json

import pytest

from tsutae.masking import (
    GENERIC_MASK,
    ID_MASK,
    RULE_ADDRESS_NUMBER,
    RULE_BEFORE_FACILITY,
    RULE_ID_LIKE,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    check_text,
    detect_identifiers,
    detect_in_patient_text,
    mask_text,
    normalize_text,
)


def _as_json(text: str) -> str:
    return json.dumps({"masked_free_text": text}, ensure_ascii=False, indent=1)


def _rules(found: list) -> set[str]:
    return {d.rule for d in found}


def _assert_not_leaked(text: str, needle: str, rule: str) -> None:
    """一次で伏せるか二次に掛かる。二次だけでも原文（文・JSON）を拾う。"""
    check = check_text(text)
    assert check.flagged or needle not in check.masked
    if needle in check.masked:
        assert detect_identifiers(_as_json(check.masked)) != []
    raw = normalize_text(text)
    assert rule in _rules(detect_in_patient_text(raw))
    assert rule in _rules(detect_identifiers(_as_json(raw)))


# ---------------------------------------------------------------------------
# 1. 仮名ID・受付番号のハイフン前後の空白・改行
# ---------------------------------------------------------------------------

_SPACED_IDS = [
    "P - DEMO0001",
    "P-\nDEMO0001",
    "P -\nDEMO0001",
    "P　-　DEMO0001",
    "P - DEMO0001",
    "p －\ndemo0001",
    "登録は P\n-\nDEMO0001 です",
]


@pytest.mark.parametrize("text", _SPACED_IDS)
def test_spaced_pseudonym_id_is_not_leaked(text: str) -> None:
    needle = "DEMO0001" if "DEMO" in text else "demo0001"
    _assert_not_leaked(text, needle, RULE_ID_LIKE)


@pytest.mark.parametrize("text", ["P - DEMO0001", "P-\nDEMO0001", "P　-　DEMO0001"])
def test_primary_masks_spaced_pseudonym_id(text: str) -> None:
    assert mask_text(normalize_text(text)).masked == ID_MASK


@pytest.mark.parametrize(
    "text", ["A - 023", "A -\n023", "A\n-\n023", "受付は A - 023 です", "A　－　023"]
)
def test_spaced_reception_number_is_detected(text: str) -> None:
    assert check_text(text).flagged
    _assert_not_leaked(text, "023", RULE_ID_LIKE)


@pytest.mark.parametrize(
    "text", ["PD - L1", "S - 1", "HER - 2", "5 - FU", "C3 - Day14"]
)
def test_spaced_drug_and_marker_names_are_not_id_like(text: str) -> None:
    assert RULE_ID_LIKE not in _rules(check_text(text).detections)


# ---------------------------------------------------------------------------
# 2. 電話番号の区切りの字数
# ---------------------------------------------------------------------------

_SPACED_PHONES = [
    "090    1234    5678",
    "090\n\n\n\n1234\n\n\n\n5678",
    "090 \n 1234\n \n5678",
    "090　　　　1234　　　　5678",
    "(03)  1234  5678",
    "03 - 1234 - 5678",
    "電話は 090 \n\n 1234 \n\n 5678 です",
]


@pytest.mark.parametrize("text", _SPACED_PHONES)
def test_phone_with_long_separators_is_not_leaked(text: str) -> None:
    _assert_not_leaked(text, "5678", RULE_LONG_DIGITS)


@pytest.mark.parametrize("text", _SPACED_PHONES[:5])
def test_primary_masks_phone_with_long_separators(text: str) -> None:
    assert GENERIC_MASK in mask_text(normalize_text(text)).masked
    assert "5678" not in mask_text(normalize_text(text)).masked


@pytest.mark.parametrize(
    "text", ["37.5\n\n\n\n36.8", "3回\n\n\n\n2回", "10:30    11:45", "11/3    11/4"]
)
def test_values_separated_by_long_whitespace_are_not_long_digits(text: str) -> None:
    assert RULE_LONG_DIGITS not in _rules(check_text(text).detections)


# ---------------------------------------------------------------------------
# 3. 住所
# ---------------------------------------------------------------------------

_SPACED_ADDRESSES = [
    ("架空町   1-2", "1-2"),
    ("架空町 1 - 2", "1 - 2"),
    ("架空町1 - 2", "1 - 2"),
    ("架空町　　　1-2", "1-2"),
    ("架空町\n\n\n1 -\n2", "2"),
    ("架空町 3 丁目", "3"),
]


@pytest.mark.parametrize(("text", "needle"), _SPACED_ADDRESSES)
def test_address_with_spaces_between_parts_is_not_leaked(
    text: str, needle: str
) -> None:
    _assert_not_leaked(text, needle, RULE_ADDRESS_NUMBER)


@pytest.mark.parametrize(
    "text",
    [
        "東京都   架空区   架空町   1-2-3",
        "東京都 架空区 架空町 1 - 2 - 3",
        "架空市 架空町 1 - 2",
    ],
)
def test_primary_masks_address_with_spaced_parts(text: str) -> None:
    masked = mask_text(text).masked
    assert masked.endswith(GENERIC_MASK)
    assert "架空町" not in masked


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("架空台1234-5-6", "1234"),
        ("架空台1-2-3", "1-2-3"),
        ("架空台 1 - 2 - 3", "1 - 2 - 3"),
        ("架空台2026-5-6", "2026"),
        ("架空台2026-13-40", "2026"),
        ("住所は 3000-1-2 です", "3000"),
        ("住所は 2026-13-1 です", "2026"),
        ("住所は 1999-2-3-4 です", "1999"),
    ],
)
def test_bare_triple_that_is_not_a_date_is_detected(text: str, needle: str) -> None:
    _assert_not_leaked(text, needle, RULE_ADDRESS_NUMBER)


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-03に受診",
        "2026-1-5から下痢",
        "記録 2026-10-27 の分",
        "２０２６－１１－０３に受診",
        "（2026-11-03）",
    ],
)
def test_real_dates_are_not_addresses(text: str) -> None:
    assert check_text(text).flagged is False
    assert detect_identifiers(_as_json(check_text(text).masked)) == []


# ---------------------------------------------------------------------------
# 4. 空白・改行の前の語（例外は改行のときだけ・明示の許可語だけ）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("みらい 病院へ行った", RULE_BEFORE_FACILITY),
        ("みらい\n病院へ行った", RULE_BEFORE_FACILITY),
        ("みらい　クリニック", RULE_BEFORE_FACILITY),
        ("みらい ちゃんに聞いた", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("みらい\nちゃんに聞いた", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("あさい 病院", RULE_BEFORE_FACILITY),
        ("さくらい\n先生", RULE_UNKNOWN_BEFORE_HONORIFIC),
        ("ゆるく 病院", RULE_BEFORE_FACILITY),
        ("ねむかった 病院", RULE_BEFORE_FACILITY),
    ],
)
def test_word_before_space_is_not_excused_by_its_ending(text: str, rule: str) -> None:
    assert rule in _rules(check_text(text).detections)
    assert rule in _rules(detect_identifiers(_as_json(check_text(text).masked)))


@pytest.mark.parametrize(
    "text",
    [
        "だるい\n医院へ",
        "つらい\n病院に電話",
        "きつかった\nクリニック",
        "だるかった\n病院へ",
        "つらく\n病院へ",
        "しんどい\n病院",
        "はやく\n病院へ",
        "つらい\n先生に相談",
        "だるい\n看護師さんに言った",
    ],
)
def test_allowed_adjective_before_line_break_is_not_detected_in_both_forms(
    text: str,
) -> None:
    check = check_text(text)
    assert check.flagged is False
    assert detect_identifiers(_as_json(check.masked)) == []


@pytest.mark.parametrize(
    "text", ["だるい 医院へ", "しんどい　病院", "つらい 先生に相談"]
)
def test_adjective_in_allow_words_is_not_detected_before_a_space(text: str) -> None:
    # 通常の空白では改行の例外は使わない。allow_words.txt の語だから通る
    assert check_text(text).flagged is False


@pytest.mark.parametrize("text", ["きつかった 病院", "だるく 病院へ"])
def test_inflected_adjective_before_a_plain_space_is_detected(text: str) -> None:
    # 活用形（許可語の形容詞から作れる形）を許すのは改行の後だけ
    assert RULE_BEFORE_FACILITY in _rules(check_text(text).detections)

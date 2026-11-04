"""masking.manual: 医師が選んだ区間の検査・伏せ字の適用と、確かめた語の許可。

- 区間は原文（生の自由記載）の code point の位置 [start, end)。範囲内・空でない・
  昇順・重ならないものだけを受け付ける（隣り合うのはよい）
- 当てると各区間が `[伏せ字]`（GENERIC_MASK）1つになる。区間の外の文字は変えない
- without_allowed: 許した部分文字列の出現に完全に含まれる検出だけを除く。許す一覧が
  空なら検出をそのまま返す
- `[伏せ字]さん` のような伏せた後の文を二次検出が再び疑わない
"""

from __future__ import annotations

import json

import pytest

from tsutae.masking import (
    GENERIC_MASK,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    Detection,
    check_text,
    detect_identifiers,
)
from tsutae.masking.manual import (
    MAX_SPANS,
    ManualSpanError,
    apply_spans,
    prompt_form,
    validate_spans,
    without_allowed,
)

RAW = "磯鷲さんにもらった漢方をのんでみた"


# --- validate_spans ---------------------------------------------------------


def test_validate_spans_accepts_sorted_disjoint_spans() -> None:
    assert validate_spans(RAW, [(0, 2), (5, 7)]) == ((0, 2), (5, 7))


def test_validate_spans_accepts_adjacent_spans_and_empty_list() -> None:
    assert validate_spans(RAW, [(0, 1), (1, 2)]) == ((0, 1), (1, 2))
    assert validate_spans(RAW, []) == ()


@pytest.mark.parametrize(
    "spans",
    [
        [(-1, 2)],  # 範囲の外（前）
        [(0, len(RAW) + 1)],  # 範囲の外（後）
        [(2, 2)],  # 空
        [(3, 2)],  # 逆順
        [(0, 3), (2, 4)],  # 重なる
        [(5, 7), (0, 2)],  # 昇順でない
        [(True, 2)],  # bool は位置ではない
        [(0.0, 2)],  # 整数でない
    ],
)
def test_validate_spans_rejects_bad_spans(spans: list[tuple[object, object]]) -> None:
    with pytest.raises(ManualSpanError):
        validate_spans(RAW, spans)  # type: ignore[arg-type]


def test_validate_spans_rejects_too_many_spans() -> None:
    text = "あ" * (MAX_SPANS + 1)
    spans = [(i, i + 1) for i in range(MAX_SPANS + 1)]
    with pytest.raises(ManualSpanError):
        validate_spans(text, spans)


def test_validate_spans_counts_code_points_not_utf16() -> None:
    text = "😀磯鷲さん"  # 絵文字は code point で1字
    assert validate_spans(text, [(1, 3)]) == ((1, 3),)
    assert apply_spans(text, [(1, 3)]) == "😀" + GENERIC_MASK + "さん"


# --- apply_spans ------------------------------------------------------------


def test_apply_spans_replaces_each_span_with_one_mask() -> None:
    assert apply_spans(RAW, [(0, 2)]) == GENERIC_MASK + "さんにもらった漢方をのんでみた"
    assert apply_spans("ab12cd34", [(2, 4), (6, 8)]) == (
        "ab" + GENERIC_MASK + "cd" + GENERIC_MASK
    )


def test_apply_spans_without_spans_returns_text_unchanged() -> None:
    assert apply_spans(RAW, []) == RAW


def test_apply_spans_does_not_touch_the_argument() -> None:
    spans = [(0, 2)]
    apply_spans(RAW, spans)
    assert spans == [(0, 2)]


def test_apply_spans_rejects_bad_spans() -> None:
    with pytest.raises(ManualSpanError):
        apply_spans(RAW, [(0, 99)])


# --- 伏せた後の文を二次検出が再び疑わない ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        GENERIC_MASK + "さんにもらった漢方",
        "昨日" + GENERIC_MASK + "さんに会った",
        GENERIC_MASK + "先生に相談した",
        "孫の" + GENERIC_MASK + "くんが来た",
        GENERIC_MASK + "ちゃんと散歩",
        GENERIC_MASK + "様から電話",
        GENERIC_MASK + " さん",
        GENERIC_MASK + "\nさん",
    ],
)
def test_masked_text_with_honorific_is_not_suspected_again(text: str) -> None:
    assert check_text(text).detections == ()
    assert detect_identifiers(json.dumps(text, ensure_ascii=False)) == []


def test_raw_text_is_suspected_but_masked_text_is_not() -> None:
    assert check_text(RAW).reason == RULE_UNKNOWN_BEFORE_HONORIFIC
    assert check_text(apply_spans(RAW, [(0, 2)])).detections == ()


# --- without_allowed --------------------------------------------------------


def test_without_allowed_returns_same_detections_when_nothing_allowed() -> None:
    found = detect_identifiers("担当者さんに聞いた")
    assert found
    assert without_allowed("担当者さんに聞いた", found, ()) == found


def test_without_allowed_drops_only_detections_inside_an_allowed_occurrence() -> None:
    text = "担当者さんと1234567に聞いた"
    found = detect_identifiers(text)
    assert [d.rule for d in found] == [RULE_UNKNOWN_BEFORE_HONORIFIC, RULE_LONG_DIGITS]
    honorific = found[0]
    allowed = [text[honorific.start : honorific.end]]
    assert without_allowed(text, found, allowed) == [found[1]]


def test_without_allowed_keeps_detection_wider_than_allowed() -> None:
    text = "番号は12345678"
    found = [Detection(RULE_LONG_DIGITS, 3, 11)]
    assert without_allowed(text, found, ["1234567"]) == found


def test_without_allowed_ignores_empty_allowed_strings() -> None:
    found = [Detection(RULE_LONG_DIGITS, 0, 7)]
    assert without_allowed("1234567", found, ["", "   "]) == found


def test_prompt_form_matches_json_dumps_inside_quotes() -> None:
    text = '磯鷲\n南"さん'
    assert prompt_form(text) == json.dumps(text, ensure_ascii=False)[1:-1]
    assert prompt_form(text) in json.dumps({"t": text}, ensure_ascii=False)

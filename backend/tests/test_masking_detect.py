"""二次の検出 `detect_identifiers` のテスト（一次の後の文に掛ける）。

一次と二次は別の規則: 一次をすり抜けたものを二次が拾い、
一次の出力そのものには二次が反応しないこと（誤検知ゼロ）を両方向で確かめる。
人名・病院名・番号は全て架空。
"""

from __future__ import annotations

import dataclasses

import pytest

from tsutae.masking import Detection, detect_identifiers, mask_text
from tsutae.masking.detect import (
    RULE_AT_MARK,
    RULE_BEFORE_FACILITY,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    RULES,
)


def _rules(text: str) -> list[str]:
    return [d.rule for d in detect_identifiers(text)]


def _spans(text: str) -> list[str]:
    return [text[d.start : d.end] for d in detect_identifiers(text)]


def test_rule_names_match_contract() -> None:
    # 契約 §5（W2b の決定）の6つ
    assert RULES == (
        "unknown_before_honorific",
        "long_digits",
        "at_mark",
        "before_facility",
        "address_number",
        "id_like",
    )


# ---------------------------------------------------------------------------
# unknown_before_honorific
# ---------------------------------------------------------------------------


def test_unknown_surname_slips_primary_and_is_detected() -> None:
    text = "磯鷲さんにもらった漢方をのんでみた"
    masked = mask_text(text).masked
    assert masked == text  # 一次はすり抜ける
    detections = detect_identifiers(masked)
    assert [d.rule for d in detections] == [RULE_UNKNOWN_BEFORE_HONORIFIC]
    assert masked[detections[0].start : detections[0].end] == "磯鷲さん"


@pytest.mark.parametrize(
    ("text", "span"),
    [
        ("磯鷲先生にきいた", "磯鷲先生"),
        ("磯鷲くんが来た", "磯鷲くん"),
        ("磯鷲様より", "磯鷲様"),
        ("磯鷲ちゃんと遊んだ", "磯鷲ちゃん"),
        ("ジョンさんに会った", "ジョンさん"),
        ("磯森さんが来た", "磯森さん"),
        ("母とさくらちゃんが来た", "さくらちゃん"),
        ("看護師の磯鷲さん", "磯鷲さん"),
        ("母と楠さん", "楠さん"),
        ("ゆうくんが来た", "ゆうくん"),
        ("孫のゆうくんが来た", "ゆうくん"),
        ("磯鷲くんからもらった", "磯鷲くん"),
        ("けんちゃんと遊んだ", "けんちゃん"),
        ("まさこさん", "まさこさん"),
        ("スズキさん", "スズキさん"),
        ("鈴木花子さん", "鈴木花子さん"),
        ("田中まり子さん", "田中まり子さん"),
        ("磯鷲看護師さんに相談した", "磯鷲看護師さん"),
    ],
)
def test_unknown_word_before_honorific_is_detected(text: str, span: str) -> None:
    assert _rules(text) == [RULE_UNKNOWN_BEFORE_HONORIFIC]
    assert _spans(text) == [span]


@pytest.mark.parametrize(
    "text",
    [
        "○○さんにもらった",
        "となりの○○さんがりんごをむいてくれた",
        "○○先生にきくことをメモした",
        "お母さんが来た",
        "お父さん",
        "母さん",
        "父さん",
        "奥さん",
        "旦那さん",
        "娘さんに送ってもらった",
        "息子さん",
        "お嫁さん",
        "お孫さん",
        "看護師さんに相談した",
        "担当の看護師さん",
        "担当看護師さん",
        "訪問看護師さんが来た",
        "薬剤師さんの説明",
        "お医者さん",
        "皆さん",
        "みなさん",
        "患者さん",
        "主治医の先生",
        "主治医先生",
        "担当の先生",
        "受付さん",
        "今日先生に言われた",
        "昨日先生に相談した",
        "新しい先生",
        "おばあちゃんが来た",
        "おじいさん",
        "赤ちゃん",
        "ごはんをたくさん食べた",
        "野菜をたくさん",
        "ちゃんと食べた",
        "薬をちゃんとのんだ",
        "様子を見る",
        "前回同様",
        "雨模様",
        "お疲れ様",
        "ご馳走様",
        "お客様",
        "どこまでいくんですか",
        "症状が長引くんです",
        "あしたいくんで",
        "ひざがかくんとなった",
        "きょうはちゃんと食べた",
        "いつもちゃんとのんでる",
        "おとなりさん",
        "八百屋さん",
        "パン屋さん",
        "朝さんぽした",
        "毎朝さんぽした",
        "Aさん",
        "ヘルパーさん",
        "お巡りさんに道をきいた",
        "店のお客さん",
        "母と奥さん",
        "○○さんのお母さん",
    ],
)
def test_allowed_words_and_placeholders_are_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# long_digits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "診察券は1234567",
        "番号123-4567",
        "09000000000",
        "090 0000 0000",
        "０１２３４５６７",
    ],
)
def test_long_digit_string_is_detected(text: str) -> None:
    assert _rules(text) == [RULE_LONG_DIGITS]


def test_hyphenated_long_digits_are_also_a_street_number() -> None:
    # N-N-N（3組以上）は W2b の決定で address_number にも当たる
    assert _rules("12-34-56-78") == [RULE_LONG_DIGITS, "address_number"]


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-09",
        "2026/11/09",
        "2026年11月9日",
        "11月9日 20時",
        "20:30",
        "2026-11-09T20:00:00+09:00",
        "37.9℃",
        "熱をはかったら37.9",
        "36.8 37.2 37.9 38.1",
        "下痢が3回",
        "123456",
        "11/1-11/9",
    ],
)
def test_dates_temperatures_short_numbers_are_not_digits(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# at_mark
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["IDは@demo_tsutae", "＠demo", "a@b"])
def test_at_mark_is_detected(text: str) -> None:
    assert _rules(text) == [RULE_AT_MARK]


def test_full_width_at_mark_is_detected() -> None:
    detections = detect_identifiers("連絡は＠のあとに")
    assert [d.rule for d in detections] == [RULE_AT_MARK]
    assert detections[0].end - detections[0].start == 1


@pytest.mark.parametrize("text", ["regimen-folfox@1", "report-format-default@2"])
def test_skill_version_like_text_is_an_at_mark(text: str) -> None:
    # 例外を作らない（患者の文に同じ形があれば漏れる）。プロンプトには Skill の版を
    # 入れず、`@` を落とした名前だけを入れる（pipeline/prompt.py）
    assert [d.rule for d in detect_identifiers(text)] == [RULE_AT_MARK]


# ---------------------------------------------------------------------------
# before_facility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "span"),
    [
        ("架空病院に行った", "架空病院"),
        ("架空中央医院", "架空中央医院"),
        ("さくらクリニック", "さくらクリニック"),
        ("架空健診センターで検査", "架空健診センター"),
        ("架空市保健センター", "架空市保健センター"),
    ],
)
def test_word_before_facility_is_detected(text: str, span: str) -> None:
    assert _rules(text) == [RULE_BEFORE_FACILITY]
    assert _spans(text) == [span]


def test_short_number_slips_primary_and_is_detected() -> None:
    masked = mask_text("番号012-3456").masked
    assert masked == "番号012-3456"
    assert _rules(masked) == [RULE_LONG_DIGITS]


def test_at_mark_without_domain_slips_primary_and_is_detected() -> None:
    masked = mask_text("LINEは@demo_tsutae").masked
    assert masked == "LINEは@demo_tsutae"
    assert _rules(masked) == [RULE_AT_MARK]


def test_center_slips_primary_and_is_detected() -> None:
    # 一次は「医療センター」だけを置換する。他の「〜センター」は二次が拾う
    masked = mask_text("架空健診センターで検査した").masked
    assert masked == "架空健診センターで検査した"
    assert _rules(masked) == [RULE_BEFORE_FACILITY]


@pytest.mark.parametrize(
    "text",
    [
        "[病院]で薬をもらった",
        "病院に行った",
        "近くの病院",
        "大きな病院",
        "きょうは病院",
        "今日病院に行った",
        "クリニックで薬をもらった",
        "医療センターに行った",
        "ホームセンターで買い物",
        "ショッピングセンター",
    ],
)
def test_bare_facility_word_is_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# 一次の出力そのものに二次が反応しない（誤検知ゼロ）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "となりの鈴木さんがりんごをむいてくれた",
        "あしたは受診日。佐藤先生にきくことをメモした",
        "田中くんと高橋ちゃんと山本様",
        "看護師の中村さんに相談した",
        "娘の電話がかわった 090-0000-0000",
        "電話は０９０－００００－００００",
        "メールはtaro.demo@example.comまで",
        "連絡先 demo_user＠example.jp",
        "東京都千代田区架空町1-2-3に住んでいる",
        "大阪府架空市本町二丁目3番4号",
        "さくらクリニックで薬をもらった",
        "架空台クリニックで口内炎のくすりをもらった",
        "昨日架空中央病院へ行った",
        "架空医療センターで検査",
        "みどり医院",
    ],
)
def test_primary_output_has_no_detection(text: str) -> None:
    masked = mask_text(text).masked
    assert masked != text
    assert detect_identifiers(masked) == []


# ---------------------------------------------------------------------------
# 戻り値の性質
# ---------------------------------------------------------------------------


def test_detections_are_sorted_and_frozen() -> None:
    text = "磯鷲さんの番号は1234567、IDは@demo、架空病院"
    detections = detect_identifiers(text)
    assert [d.rule for d in detections] == [
        RULE_UNKNOWN_BEFORE_HONORIFIC,
        RULE_LONG_DIGITS,
        RULE_AT_MARK,
        RULE_BEFORE_FACILITY,
    ]
    assert detections == sorted(detections, key=lambda d: (d.start, d.end))
    assert all(isinstance(d, Detection) and d.start < d.end for d in detections)
    with pytest.raises(dataclasses.FrozenInstanceError):
        detections[0].rule = "x"  # type: ignore[misc]


def test_empty_text_has_no_detection() -> None:
    assert detect_identifiers("") == []


def test_non_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        detect_identifiers(123)  # type: ignore[arg-type]

"""W1 独立レビューの指摘（verify_masking）に対する回帰テスト。

各指摘について両方向を確かめる:
- 検出すべきもの: 一次（mask_text）→二次（detect_identifiers）を通して、識別子が
  伏せられるか、二次に掛かる（送らない）こと
- 検出してはいけないもの: 続柄・職種・一般語・症状の文に二次が反応しないこと

人名・病院名・番号は全て架空。
"""

from __future__ import annotations

import time

import pytest

from tsutae.masking import check_text, detect_identifiers, mask_text
from tsutae.masking.detect import (
    RULE_BEFORE_FACILITY,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
)


def _slips_primary_and_is_detected(text: str, rule: str) -> None:
    """一次は文を変えず、二次が rule で検出する（二次が網羅性を足している）。"""
    masked = mask_text(text).masked
    assert masked == text
    assert rule in [d.rule for d in detect_identifiers(masked)]


def _is_caught(text: str, identifier: str) -> bool:
    """一次で伏せられた（識別子が残らない）か、二次に掛かったか。"""
    check = check_text(text)
    return identifier not in check.masked or check.flagged


# ---------------------------------------------------------------------------
# critical: ひらがなの姓が「とうさん」「じいさん」等の許可語に後ろから一致する
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "さとうさんがきた",
        "かとうさんにもらった",
        "いとうさん",
        "ごとうさん",
        "ないとうさん",
        "ふじいさんがきた",
        "さとうちゃん",
        "磯鷲おばあちゃんがきた",
        "となりのさとうさんがきた",
    ],
)
def test_hiragana_surname_ending_like_relation_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    ("text", "span"),
    [("さとうさんがきた", "さとうさん"), ("ふじいさんがきた", "ふじいさん")],
)
def test_hiragana_surname_span_covers_whole_word(text: str, span: str) -> None:
    detections = detect_identifiers(text)
    assert [text[d.start : d.end] for d in detections] == [span]


@pytest.mark.parametrize(
    "text",
    [
        "うちのとうさん",
        "とうさんが来た",
        "おとうさんが来た",
        "となりのおばあさん",
        "やさしいおばあさんだった",
        "今日おばあちゃんが来た",
        "母とおじいちゃん",
        "ごはんをたくさん食べた",
        "かなりたくさん食べた",
        "すごくたくさんでた",
        "おとなりさん",
        "うちのばあちゃん",
    ],
)
def test_relation_words_after_boundary_are_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# critical: ひらがなの施設名（二次が一次と同じ関数を使っていた）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "みらいクリニックで薬",
        "あおい病院",
        "みなとクリニック",
        "あさがおクリニック",
        "かえでクリニック",
        "ひがし病院",
        "はるかクリニック",
        "家のちかくのみなとクリニック",
        "あしたはあおい病院",
    ],
)
def test_hiragana_facility_slips_primary_and_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_BEFORE_FACILITY)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("ことぶき病院", "[病院]"), ("のぞみクリニックで薬", "[病院]で薬")],
)
def test_hiragana_facility_with_particle_char_is_not_half_masked(
    text: str, expected: str
) -> None:
    check = check_text(text)
    assert check.masked == expected
    assert check.detections == ()


def test_half_masked_hiragana_facility_is_detected() -> None:
    # 一次は名前の中の「と」で切って「母とこと[病院]」と半端に伏せる。二次が拾う
    check = check_text("母とことぶき病院へ")
    assert check.masked == "母とこと[病院]へ"
    assert [d.rule for d in check.detections] == [RULE_BEFORE_FACILITY]


@pytest.mark.parametrize(
    "text",
    [
        "母とさくらクリニックへ",
        "おかあさんとさくらクリニックへ",
        "きのうさくらクリニック",
        "あしたもさくらクリニック",
        "熱がでたのでさくらクリニックに電話",
        "ちかくのさくら病院",
    ],
)
def test_placeholder_after_common_words_is_not_detected(text: str) -> None:
    check = check_text(text)
    assert "[病院]" in check.masked
    assert check.detections == ()


@pytest.mark.parametrize(
    "text",
    [
        "近くの病院",
        "ちかくの病院",
        "いつもの病院",
        "かかりつけ病院",
        "おなじ病院",
        "きょうは病院",
        "あしたもかかりつけの病院",
        "ねつがでたら病院に電話",
        "ねつがでたので病院",
        "おなかがいたいから病院へ",
        "おかあさんと病院へ",
        "ねつがでたらおかあさんと病院へいった",
        "熱が出たので病院へ",
        "母と病院へ行った",
        "くすりをもらいに病院へ",
        "大きな病院",
        "新しい病院",
        "とてもいい病院",
        "具合がわるくて病院",
    ],
)
def test_bare_facility_after_common_hiragana_is_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []
    assert check_text(text).detections == ()


# ---------------------------------------------------------------------------
# high: 名前＋様（様の後読みに 一・多 が入っていた）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "name"), [("鈴木健一様あて", "健一"), ("喜多様より", "喜多")]
)
def test_name_ending_with_ichi_or_ta_before_sama_is_caught(
    text: str, name: str
) -> None:
    assert check_text(text).flagged
    assert _is_caught(text, name)


def test_unknown_name_before_sama_slips_primary_and_is_detected() -> None:
    _slips_primary_and_is_detected("磯一様", RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    "text", ["前回同様", "多様な症状", "雨模様", "一様に赤い", "多種多様"]
)
def test_sama_inside_common_words_is_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# high: 1字の許可語（屋・科 等）・1字姓＋職種
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "林看護師さんに相談した",
        "森薬剤師さん",
        "守屋さん",
        "古屋さん",
        "仁科さん",
        "保科さん",
    ],
)
def test_short_allow_word_does_not_cover_a_surname(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    "text", ["さとう看護師さん", "すずき薬剤師さんに相談", "やまもと看護師さん"]
)
def test_hiragana_surname_before_role_word_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    "text",
    [
        "やさしい看護師さん",
        "きょうはやさしい看護師さんだった",
        "優しい看護師さん",
        "優しいばあちゃん",
        "わかい薬剤師さん",
    ],
)
def test_adjective_before_role_word_is_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "お客さん",
        "店のお客さん",
        "八百屋さん",
        "訪問看護師さんが来た",
        "叔母さんが来た",
        "新人看護師さん",
        "外科医先生",
        "植木屋さん",
        "美容師さん",
    ],
)
def test_roles_and_relations_are_still_allowed(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# high: くんの前のひらがな名（と・も 等で切っていた）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "はるとくんが来た",
        "孫のゆうとくん",
        "みなとくん",
        "かいとくんと遊んだ",
        "ともくん",
        "さとうくん",
        "孫のゆう太くん",
    ],
)
def test_hiragana_name_before_kun_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    "text",
    [
        "ひざがかくんとなった",
        "胸がちくんとした",
        "くすりをごくんとのんだ",
        "むねがどくんどくんした",
        "ひざががくんとなった",
    ],
)
def test_onomatopoeia_with_kun_is_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# high: 先生・様の前のひらがなの姓
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "さとう先生にきいた",
        "すずき先生",
        "たなか様",
        "主治医のすずき先生",
        "やまもと先生",
    ],
)
def test_hiragana_surname_before_sensei_or_sama_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    "text",
    [
        "優しい先生",
        "新しい先生",
        "やさしい先生だった",
        "あたらしい先生",
        "いつもの先生",
        "おかあさんと先生に会った",
        "いい先生",
        "わかい先生",
        "お疲れ様でした",
        "おつかれ様でした",
    ],
)
def test_adjectives_before_sensei_are_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# high: くんの後ろの です・で・だ・か（直前の語を見ずに除いていた）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "磯鷲くんです",
        "孫の磯鷲くんで、",
        "それは磯鷲くんだった",
        "磯鷲くんか",
        "孫のゆうくんです",
        "ゆうくんだよ",
    ],
)
def test_name_kun_followed_by_desu_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    "text",
    [
        "症状が長引くんです",
        "あしたいくんで",
        "どこまでいくんですか",
        "足がふらつくんです",
        "くすりがきくんですか",
        "あした行くんで",
        "ずっと続くんです",
        "きょうも病院にいくんだ",
    ],
)
def test_verb_ku_n_desu_is_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# high: 電話番号の区切り（. ． ・ / ／）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "number",
    [
        "090.1234.5678",
        "090/1234/5678",
        "090・1234・5678",
        "０９０．１２３４．５６７８",
        "03／1234／5678",
    ],
)
def test_phone_with_dot_or_slash_is_masked(number: str) -> None:
    result = mask_text(f"電話 {number} です")
    assert result.masked == "電話 [伏せ字] です"
    assert result.counts["phone"] == 1


def test_card_number_with_dot_slips_primary_and_is_detected() -> None:
    _slips_primary_and_is_detected("診察券1234.5678", RULE_LONG_DIGITS)


@pytest.mark.parametrize(
    "text",
    [
        "37.9℃",
        "36.8 37.2 37.9 38.1",
        "0.5錠",
        "2026.11.09に受診",
        "体重52.3kg",
        "1/2錠",
        "11/1-11/9",
        "2026-11-09T20:00:00.123456+09:00",
    ],
)
def test_decimals_and_dates_are_not_phone_or_digits(text: str) -> None:
    check = check_text(text)
    assert check.masked == text
    assert check.detections == ()


# ---------------------------------------------------------------------------
# medium: 敬称の前の空白・改行、ローマ字の名前
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("鈴木 さんが来た", "○○ さんが来た"), ("佐藤　先生", "○○　先生")],
)
def test_dictionary_surname_with_space_is_masked(text: str, expected: str) -> None:
    check = check_text(text)
    assert check.masked == expected
    assert check.detections == ()


@pytest.mark.parametrize(
    "text",
    [
        "磯鷲\nさん",
        "磯鷲 さん",
        "Tanakaさんが来た",
        "Ｓａｔｏさん",
        "John先生",
        "Tanaka さん",
    ],
)
def test_name_separated_by_space_or_in_latin_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize("text", ["Aさん", "毎朝 さんぽした", "○○ さん"])
def test_single_letter_and_walk_are_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# medium: 契約の5つ以外の敬称（せんせい・さま・君・氏・殿）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("佐藤せんせいにきいた", "○○せんせいにきいた"),
        ("佐藤さまより", "○○さまより"),
        ("田中君が来た", "○○君が来た"),
        ("佐藤氏", "○○氏"),
        ("佐藤殿", "○○殿"),
    ],
)
def test_other_honorifics_are_masked(text: str, expected: str) -> None:
    check = check_text(text)
    assert check.masked == expected
    assert check.detections == ()


@pytest.mark.parametrize(
    "text",
    ["磯鷲せんせい", "磯鷲さまより", "磯鷲君が来た", "磯鷲氏", "磯鷲殿"],
)
def test_unknown_name_with_other_honorific_is_detected(text: str) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    "text",
    [
        "おかげさまで元気",
        "ごちそうさまでした",
        "おつかれさまでした",
        "お日さまがまぶしい",
        "氏名を書いた",
        "彼氏が来た",
        "さまざまな症状",
        "熱をさます",
        "主治医のせんせい",
        "やさしいせんせい",
    ],
)
def test_other_honorific_like_words_are_not_detected(text: str) -> None:
    assert detect_identifiers(text) == []


# ---------------------------------------------------------------------------
# medium: 辞書の姓の左に別の漢字が続く（半端に伏せていた）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "小山田さんが来た",
        "大和田さん",
        "小野田さん",
        "小早川さん",
        "小山内さん",
        "上中村さん",
        "磯鷲田中さん",
        "ジョン鈴木さん",
    ],
)
def test_longer_name_ending_with_surname_is_left_whole_and_detected(
    text: str,
) -> None:
    _slips_primary_and_is_detected(text, RULE_UNKNOWN_BEFORE_HONORIFIC)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("今日佐藤先生に聞いた", "今日○○先生に聞いた"),
        ("主治医佐藤先生", "主治医○○先生"),
        ("担当鈴木さん", "担当○○さん"),
    ],
)
def test_surname_after_allowed_word_is_masked(text: str, expected: str) -> None:
    check = check_text(text)
    assert check.masked == expected
    assert check.detections == ()


# ---------------------------------------------------------------------------
# medium: 都道府県も丁目も無い N-N を住所にしない
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["毎日市販薬1-2錠のんだ", "毎日市販薬を2-3錠"])
def test_two_number_pair_without_prefecture_is_not_an_address(text: str) -> None:
    result = mask_text(text)
    assert result.masked == text
    assert result.counts["address"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "架空市本町１－２－３",
        "架空市本町2丁目3",
        "東京都架空市本町1-2",
        "架空市中区架空町1-2",
        "架空市本町1-2",
    ],
)
def test_address_with_marks_prefecture_or_two_units_is_still_masked(
    text: str,
) -> None:
    result = mask_text(text)
    assert result.masked == "[伏せ字]"
    assert result.counts["address"] == 1


def test_city_level_address_with_pair_is_masked_in_sentence() -> None:
    result = mask_text("架空市中区架空町1-2に住んでいる")
    assert result.masked == "[伏せ字]に住んでいる"


# ---------------------------------------------------------------------------
# medium: 誤検知（ひらがなの数・一般的な呼び方・施設の種類）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "げりがさんかいでた",
        "よるさんじにおきた",
        "ねつがさんにちつづいた",
        "げりさんかい",
        "ねつがさんじゅうはちどあった",
        "大工さんが来た",
        "植木屋さん",
        "郵便屋さんがきた",
        "新聞屋さん",
        "民生委員さん",
        "お地蔵さん",
        "ご先祖様",
        "包括支援センターに相談",
        "デイサービスセンターに行った",
        "美容師さんに切ってもらった",
    ],
)
def test_common_false_positives_are_not_detected(text: str) -> None:
    assert check_text(text).detections == ()


def test_specific_support_center_is_still_detected() -> None:
    _slips_primary_and_is_detected(
        "架空市地域包括支援センターに相談", RULE_BEFORE_FACILITY
    )


def test_hiragana_counter_does_not_hide_a_name() -> None:
    _slips_primary_and_is_detected("磯鷲さんが来た", RULE_UNKNOWN_BEFORE_HONORIFIC)


# ---------------------------------------------------------------------------
# low: 中黒・時を表す語の前の施設語
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "点滴の日・病院で点滴した",
        "検査・病院",
        "点滴の日・投与日・病院",
        "夜中病院に電話",
        "朝病院へ",
        "先週末病院へ",
        "おなじ病院",
        "かかりつけ病院",
    ],
)
def test_time_words_and_middle_dot_before_facility_are_kept(text: str) -> None:
    check = check_text(text)
    assert check.masked == text
    assert check.detections == ()


def test_katakana_name_with_middle_dot_is_detected() -> None:
    _slips_primary_and_is_detected(
        "ジョン・スミスさんが来た", RULE_UNKNOWN_BEFORE_HONORIFIC
    )


# ---------------------------------------------------------------------------
# 2000字程度の入力で遅くならない（ReDoS を起こさない）
# ---------------------------------------------------------------------------


_LONG_INPUTS = [
    "鷲" * 2000 + "さん",
    "鷲" * 2000 + "病院",
    "さ" * 2000 + "病院",
    "の" * 2000 + "くん",
    "とも" * 1000 + "くん",
    "おかあさんと" * 330 + "病院",
    "さん" * 1000,
    "くん" * 1000,
    "様" * 2000,
    "1." * 1000,
    "0-" * 1000,
    "架空市" * 600 + "1-2",
    "市" * 2000,
    "市" * 1990 + "1-2-3",
    "架空市中区" * 400 + "1-2",
    "a@" * 1000,
    ("となりの鈴木さんが090-0000-0000に電話。架空病院で37.9。さくらクリニック。" * 50)[
        :2000
    ],
]


@pytest.mark.parametrize("text", _LONG_INPUTS, ids=range(len(_LONG_INPUTS)))
def test_long_input_is_fast(text: str) -> None:
    check_text("鈴木さん")  # 辞書の読み込み（初回だけ）を計測から外す
    started = time.perf_counter()
    check_text(text)
    assert time.perf_counter() - started < 0.1

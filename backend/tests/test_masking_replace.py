"""一次の伏せ字（置換）`mask_text` のテスト。

人名・病院名・番号・住所は全て架空（「架空町」「磯鷲」など）。
"""

from __future__ import annotations

import dataclasses

import pytest

from tsutae.masking import MaskResult, mask_text
from tsutae.masking.replace import load_allow_words, load_surnames

COUNT_KEYS = {"id", "name", "phone", "email", "address", "hospital"}


# ---------------------------------------------------------------------------
# 辞書
# ---------------------------------------------------------------------------


def test_surnames_dictionary_is_common_japanese_surnames() -> None:
    surnames = load_surnames()
    assert 250 <= len(surnames) <= 400
    assert len(set(surnames)) == len(surnames)
    assert surnames[:3] == ("佐藤", "鈴木", "高橋")
    for name in ("田中", "佐々木", "長谷川", "五十嵐", "林", "森"):
        assert name in surnames
    # テストに使う架空の姓は辞書に無い
    for fictional in ("磯鷲", "磯森", "架空"):
        assert fictional not in surnames


def test_allow_words_include_relations_and_roles() -> None:
    words = load_allow_words()
    for word in ("お母さん", "娘さん", "看護師さん", "薬剤師さん", "皆さん", "主治医"):
        assert word in words


# ---------------------------------------------------------------------------
# 人名（姓辞書＋敬称）
# ---------------------------------------------------------------------------


def test_dictionary_surname_with_san_is_masked() -> None:
    result = mask_text("となりの鈴木さんがりんごをむいてくれた")
    assert result.masked == "となりの○○さんがりんごをむいてくれた"
    assert result.counts["name"] == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("佐藤先生にきくことをメモした", "○○先生にきくことをメモした"),
        ("田中くんが来た", "○○くんが来た"),
        ("高橋ちゃんと遊んだ", "○○ちゃんと遊んだ"),
        ("山本様より", "○○様より"),
        ("佐々木さんに会った", "○○さんに会った"),
        ("長谷川さん", "○○さん"),
        ("今日佐藤先生に聞いた", "今日○○先生に聞いた"),
        ("母と森さんが来た", "母と○○さんが来た"),
    ],
)
def test_surname_is_masked_and_honorific_kept(text: str, expected: str) -> None:
    assert mask_text(text).masked == expected


def test_multiple_names_are_counted() -> None:
    result = mask_text("鈴木さんと佐藤先生と中村さん")
    assert result.masked == "○○さんと○○先生と○○さん"
    assert result.counts["name"] == 3


def test_unknown_surname_passes_primary() -> None:
    # 辞書にない架空の姓は一次をすり抜ける（二次で検出される）
    assert mask_text("磯鷲さんにもらった漢方").masked == "磯鷲さんにもらった漢方"


def test_single_kanji_surname_inside_longer_name_is_left_whole() -> None:
    # 「森」は辞書にあるが「磯森」は無い。「磯○○さん」と半端に伏せない
    assert mask_text("磯森さんが来た").masked == "磯森さんが来た"


def test_surname_without_honorific_is_kept() -> None:
    assert mask_text("中山の景色を見た").masked == "中山の景色を見た"


@pytest.mark.parametrize(
    "text",
    [
        "お母さんが来た",
        "お父さんと話した",
        "娘さんに送ってもらった",
        "息子さんが来た",
        "看護師さんに相談した",
        "薬剤師さんの説明",
        "お医者さんに言った",
        "皆さんにお世話になった",
        "主治医の先生にきいた",
        "担当の先生",
        "ごはんをたくさん食べた",
        "様子を見る",
    ],
)
def test_relations_and_roles_are_not_masked(text: str) -> None:
    result = mask_text(text)
    assert result.masked == text
    assert result.counts["name"] == 0


# ---------------------------------------------------------------------------
# 電話・メール・住所
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "number",
    [
        "090-0000-0000",
        "09000000000",
        "03-0000-0000",
        "0120-000-000",
        "090 0000 0000",
        "03(0000)0000",
        "０９０－００００－００００",
    ],
)
def test_phone_is_masked(number: str) -> None:
    result = mask_text(f"電話は{number}です")
    assert result.masked == "電話は[伏せ字]です"
    assert result.counts["phone"] == 1


def test_international_phone_is_masked() -> None:
    result = mask_text("電話は+81-90-0000-0000です")
    assert result.masked == "電話は[伏せ字]です"
    assert result.counts["phone"] == 1


def test_short_zero_leading_number_is_not_a_phone() -> None:
    # 0 始まりでも 10〜11 桁でなければ電話としては伏せない（二次の long_digits が拾う）
    result = mask_text("番号012-3456")
    assert result.masked == "番号012-3456"
    assert result.counts["phone"] == 0


def test_phone_in_synthetic_style_sentence() -> None:
    result = mask_text("娘の電話がかわった 090-0000-0000")
    assert result.masked == "娘の電話がかわった [伏せ字]"


@pytest.mark.parametrize(
    "text",
    ["100000円かかった", "下痢が3回", "体温37.9℃", "2026-11-09に受診", "0.5錠"],
)
def test_non_phone_numbers_are_kept(text: str) -> None:
    result = mask_text(text)
    assert result.masked == text
    assert result.counts["phone"] == 0


@pytest.mark.parametrize(
    "address", ["taro.demo@example.com", "demo_user＠example.jp", "a+b@example.co.jp"]
)
def test_email_is_masked(address: str) -> None:
    result = mask_text(f"メールは{address}まで")
    assert result.masked == "メールは[伏せ字]まで"
    assert result.counts["email"] == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("東京都千代田区架空町1-2-3に住んでいる", "[伏せ字]に住んでいる"),
        ("住所は大阪府架空市本町二丁目3番4号です", "住所は[伏せ字]です"),
        ("北海道架空市架空町1丁目2番地", "[伏せ字]"),
        ("架空市本町１－２－３", "[伏せ字]"),
    ],
)
def test_address_is_masked(text: str, expected: str) -> None:
    result = mask_text(text)
    assert result.masked == expected
    assert result.counts["address"] == 1


@pytest.mark.parametrize(
    "text",
    [
        "東京へ行った",
        "大阪の娘の家に泊まった",
        "横浜市に住んでいる",
        "東京都に行って2回目の点滴",
        "京都で紅葉を見た",
    ],
)
def test_region_names_are_kept(text: str) -> None:
    result = mask_text(text)
    assert result.masked == text
    assert result.counts["address"] == 0


# ---------------------------------------------------------------------------
# 病院名
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("さくらクリニックで薬をもらった", "[病院]で薬をもらった"),
        ("架空台クリニックで口内炎のくすり", "[病院]で口内炎のくすり"),
        ("架空中央病院に入院した", "[病院]に入院した"),
        ("みどり医院へ行った", "[病院]へ行った"),
        ("架空医療センターで検査", "[病院]で検査"),
        ("ABCクリニック", "[病院]"),
        ("昨日架空病院へ行った", "昨日[病院]へ行った"),
        ("熱がでたのでさくらクリニックに電話", "熱がでたので[病院]に電話"),
    ],
)
def test_facility_name_is_masked(text: str, expected: str) -> None:
    result = mask_text(text)
    assert result.masked == expected
    assert result.counts["hospital"] == 1


@pytest.mark.parametrize(
    "text",
    [
        "病院に行った",
        "近くの病院",
        "クリニックで薬をもらった",
        "大きな病院",
        "新しい病院",
        "きょうは病院",
        "きのう病院へ行った",
        "今日病院に行った",
        "あした病院",
        "熱が出たら病院に電話する",
    ],
)
def test_bare_facility_word_is_kept(text: str) -> None:
    result = mask_text(text)
    assert result.masked == text
    assert result.counts["hospital"] == 0


# ---------------------------------------------------------------------------
# 残すもの・全体の性質
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-09",
        "11月9日 20時",
        "20:30に熱をはかった",
        "夕方さむけがして熱をはかったら37.9。",
        "体温37.9℃",
        "あしたは2回目の点滴",
        "ポンプを外した日からずっとだるい",
    ],
)
def test_dates_times_and_temperatures_are_kept(text: str) -> None:
    result = mask_text(text)
    assert result.masked == text
    assert sum(result.counts.values()) == 0


def test_counts_always_have_all_keys() -> None:
    assert set(mask_text("").counts) == COUNT_KEYS
    assert mask_text("").masked == ""


def test_mask_is_idempotent() -> None:
    text = "鈴木さんと架空中央病院へ。電話090-0000-0000、a@example.com"
    once = mask_text(text).masked
    assert mask_text(once).masked == once


def test_result_is_frozen() -> None:
    result = mask_text("鈴木さん")
    assert isinstance(result, MaskResult)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.masked = "x"  # type: ignore[misc]


def test_non_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        mask_text(None)  # type: ignore[arg-type]

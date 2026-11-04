"""未処理の記載（D6）の印: 疑われた語の原文の中の位置（tsutae.api.doctor_marks）。

二次の検出は一次（伏せ字）の後の文に掛かるので、位置はそのままでは原文に合わない。
検出された区間の文字列を原文から探して、原文の位置（code point の [start, end)）を返す。
見つからない区間は印を付けない（位置を推測しない）。症例は全て合成。
"""

from __future__ import annotations

import pytest

from tsutae.api.doctor_marks import suspect_marks


def _marked(text: str, marks: list[dict[str, int]]) -> list[str]:
    return [text[m["start"] : m["end"]] for m in marks]


def test_unknown_name_before_honorific() -> None:
    text = "磯鷲さんにもらった漢方をのんでみた"
    assert suspect_marks(text, []) == [{"start": 0, "end": 4}]


def test_position_after_first_pass_replacement_is_in_original() -> None:
    """一次で「田中さん」→「○○さん」（長さが変わる）でも、後ろの語の位置は原文のもの。"""
    text = "田中さんと磯鷲さんに会った"
    assert _marked(text, suspect_marks(text, [])) == ["磯鷲さん"]


def test_several_rules() -> None:
    text = "電話は 1234567 です。磯鷲さんより"
    assert _marked(text, suspect_marks(text, [])) == ["1234567", "磯鷲さん"]


def test_known_identifier_literals() -> None:
    text = "紙に P-DEMO0001 と a-023 が書いてあった"
    marks = suspect_marks(text, ["P-DEMO0001", "A-023"])
    assert _marked(text, marks) == ["P-DEMO0001", "a-023"]


def test_overlapping_marks_are_merged() -> None:
    text = "紙に P-DEMO0001 と書いた"
    marks = suspect_marks(text, ["P-DEMO0001"])  # id_like と同じ区間
    assert _marked(text, marks) == ["P-DEMO0001"]


def test_positions_are_code_points() -> None:
    text = "😀磯鷲さん"
    assert suspect_marks(text, []) == [{"start": 1, "end": 5}]


@pytest.mark.parametrize("text", ["", "おなかがゆるい日が続いた", "田中さんに会った"])
def test_nothing_suspected(text: str) -> None:
    assert suspect_marks(text, []) == []


def test_empty_literals_are_ignored() -> None:
    assert suspect_marks("おなかがゆるい", ["", "  "]) == []

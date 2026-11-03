"""二次 id_like の追加の形（仕上げのレビュー指摘5）。

区切り無し（英字1〜2字＋数字3字以上: A023）と、下線・中黒の区切り（P_DEMO0001・A・023。
後ろに数字を含むものだけ。JSON のキー by_proxy 等を拾わないため）。症例は全て合成。
"""

from __future__ import annotations

import json

import pytest

from tsutae.masking import RULE_ID_LIKE, detect_identifiers, detect_in_patient_text


def _rules(text: str) -> list[str]:
    return [d.rule for d in detect_in_patient_text(text)]


@pytest.mark.parametrize(
    "text",
    [
        "受付はA023番だった",
        "AB1234",
        "ａ０２３",
        "IDはP_DEMO0001",
        "受付票はA・023",
        "A ･ 023",
        "P＿DEMO0001",
    ],
)
def test_id_like_without_hyphen_is_detected(text: str) -> None:
    assert RULE_ID_LIKE in _rules(text)


@pytest.mark.parametrize(
    "text",
    [
        "A02",  # 数字2字
        "ABC123",  # 英字3字
        "HbA1c",
        "B12を飲んだ",
        "S1",
        "5FU",
        "by_proxy",  # 後ろに数字が無い
        "DB・API",
        "LF・CRLF",
        "day1_date",
        "37.5度",
    ],
)
def test_other_forms_are_not_id_like(text: str) -> None:
    assert RULE_ID_LIKE not in _rules(text)


def test_prompt_json_keys_are_not_id_like() -> None:
    prompt = json.dumps(
        {
            "entries": [
                {"entry_no": 1, "by_proxy": False, "too_sick": False, "day": 3}
            ],
            "schedule": {"day1_date": "2026-10-27", "pump_removal_date": None},
        },
        ensure_ascii=False,
    )
    assert detect_identifiers(prompt) == []


def test_escaped_line_break_before_digits_is_not_id_like() -> None:
    # 依頼文の JSON では改行が \\n。n と数字をつないで A023 の形にしない
    prompt = json.dumps({"t": "だるい\n2026年"}, ensure_ascii=False)
    assert RULE_ID_LIKE not in [d.rule for d in detect_identifiers(prompt)]

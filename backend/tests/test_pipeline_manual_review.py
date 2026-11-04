"""医師の伏せ字の再検出（pipeline.manual_review）。D6 の「伏せ字を確かめる」と保存で使う。

- 送られる文（伏せた後。正規化・一次の後）と、まだ疑われる区間（その文の位置）を返す
- 疑いが残り、全ての位置が分かり、仮名ID・受付番号でなければ「確かめて送れる」
- 確かめた区間を DoctorMask.allowed にすれば、変換の入力（mask_entry_text）でも送れる
"""

from __future__ import annotations

import pytest

from tsutae.masking import (
    GENERIC_MASK,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
)
from tsutae.masking.manual import ManualSpanError
from tsutae.pipeline.inputs import REASON_KNOWN_IDENTIFIER, mask_entry_text
from tsutae.pipeline.manual_review import confirmed_mask, review_doctor_mask
from tsutae.schemas import DoctorMask, TextSpan

RAW = "磯鷲さんにもらった漢方をのんでみた"
LITERALS = ("P-DEMO0001", "A-023")


def test_clean_after_masking_is_sendable() -> None:
    review = review_doctor_mask(RAW, [(0, 2)], LITERALS)
    assert review.masked_text == GENERIC_MASK + RAW[2:]
    assert review.suspects == ()
    assert review.reason is None
    assert review.confirmable is False


def test_remaining_suspects_are_reported_in_masked_text_positions() -> None:
    review = review_doctor_mask(RAW, [], LITERALS)
    assert review.masked_text == RAW
    assert [(s.rule, s.start, s.end) for s in review.suspects] == [
        (RULE_UNKNOWN_BEFORE_HONORIFIC, 0, 4)
    ]
    assert review.reason == RULE_UNKNOWN_BEFORE_HONORIFIC
    assert review.confirmable is True


def test_positions_follow_primary_masking() -> None:
    # 一次で長さが変わる（田中さん → ○○さん）。位置は送られる文のもの
    text = "田中さんと1234567"
    review = review_doctor_mask(text, [], LITERALS)
    assert review.masked_text.startswith("○○さん")
    suspect = review.suspects[0]
    assert suspect.rule == RULE_LONG_DIGITS
    assert review.masked_text[suspect.start : suspect.end] == "1234567"


def test_known_identifier_is_not_confirmable() -> None:
    review = review_doctor_mask("受付はA-023でした", [], LITERALS)
    assert review.reason == REASON_KNOWN_IDENTIFIER
    assert review.confirmable is False
    assert any(review.masked_text[s.start : s.end] == "A-023" for s in review.suspects)
    masked = review_doctor_mask("受付はA-023でした", [(3, 8)], LITERALS)
    assert masked.reason is None


def test_bad_spans_raise() -> None:
    with pytest.raises(ManualSpanError):
        review_doctor_mask(RAW, [(0, 99)], LITERALS)


@pytest.mark.parametrize(
    ("text", "spans"),
    [
        (RAW, []),
        ("磯鷲さんと鶯谷さん", [(0, 2)]),
        ("担当者さんに聞いた", []),
        ("番号は1234567です", []),
    ],
)
def test_confirmed_mask_lets_the_pipeline_send_it(
    text: str, spans: list[tuple[int, int]]
) -> None:
    review = review_doctor_mask(text, spans, LITERALS)
    assert review.confirmable
    mask = confirmed_mask(spans, review)
    assert mask.confirmed_clear is True
    outcome = mask_entry_text(text, mask)
    assert outcome.reason is None
    assert outcome.masked == review.masked_text
    assert outcome.allowed == tuple(
        review.masked_text[s.start : s.end] for s in review.suspects
    )


def test_confirmed_mask_refuses_when_not_confirmable() -> None:
    review = review_doctor_mask("受付はA-023でした", [], LITERALS)
    with pytest.raises(ValueError):
        confirmed_mask([], review)


def test_plain_mask_keeps_spans_only() -> None:
    review = review_doctor_mask(RAW, [(0, 2)], LITERALS)
    assert confirmed_mask([(0, 2)], review, confirmed=False) == DoctorMask(
        spans=[TextSpan(start=0, end=2)]
    )

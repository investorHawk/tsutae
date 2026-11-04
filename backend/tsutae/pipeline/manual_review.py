"""医師の伏せ字の再検出（D6 の「伏せ字を確かめる」と保存）。症例は全て合成。

医師は文を書かず、原文の区間だけを選ぶ。ここでは区間を当てた後の文に、変換の入力
（`pipeline.inputs`）と同じ検査を掛け直し、院内画面に見せる形にする:

1. 生の原文に区間を当てる（`masking.manual.apply_spans`。合わなければ ManualSpanError）
2. 仮名ID・受付番号（literals）を含めば known_identifier（確かめても送れない）
3. check_text（正規化 → 一次 → 二次）の検出。位置は送られる文（masked）のもの
4. 3 で何も出なければ、依頼文の形（JSON）での二次。区間は送られる文の中で探し直す
   （エスケープをまたいで見つからない区間があれば「確かめて送る」はできない）

`confirmed_mask` は保存する DoctorMask を作る。確かめた（confirmed）記録は、今まだ
疑われている区間**ちょうど**を allowed にする（サーバーが計算する。画面からは送らない）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from tsutae.masking import check_text, detect_identifiers
from tsutae.masking.manual import Span, apply_spans
from tsutae.pipeline.inputs import REASON_KNOWN_IDENTIFIER, has_known_literal
from tsutae.schemas import DoctorMask, TextSpan

__all__ = ["MaskReview", "Suspect", "confirmed_mask", "review_doctor_mask"]


@dataclass(frozen=True)
class Suspect:
    rule: str
    start: int  # 送られる文（MaskReview.masked_text）の位置
    end: int


@dataclass(frozen=True)
class MaskReview:
    masked_text: str  # 送られる文（伏せた後。正規化・一次の後）
    suspects: tuple[Suspect, ...]
    reason: str | None  # 送れない理由（無ければそのまま送れる）
    confirmable: bool  # 「個人を特定する語は無いことを確かめた」で送れるか


def _literal_suspects(masked: str, literals: Sequence[str]) -> list[Suspect]:
    found: list[Suspect] = []
    for literal in literals:
        cleaned = literal.strip()
        if not cleaned:
            continue
        pattern = re.compile(re.escape(cleaned), re.IGNORECASE)
        found.extend(
            Suspect(REASON_KNOWN_IDENTIFIER, m.start(), m.end())
            for m in pattern.finditer(masked)
        )
    return found


def _decode(segment: str) -> str | None:
    try:
        value = json.loads(f'"{segment}"')
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def _prompt_suspects(masked: str) -> tuple[list[Suspect], bool]:
    """依頼文の形での検出を送られる文の位置に直す。(区間, 全て位置が分かったか)。"""
    in_prompt = json.dumps(masked, ensure_ascii=False)
    found: list[Suspect] = []
    located = True
    for d in detect_identifiers(in_prompt):
        segment = _decode(in_prompt[d.start : d.end])
        start = masked.find(segment) if segment and segment.strip() else -1
        if start < 0 or segment is None:
            located = False
            continue
        found.append(Suspect(d.rule, start, start + len(segment)))
    return found, located


def _ordered(suspects: list[Suspect]) -> tuple[Suspect, ...]:
    return tuple(sorted(set(suspects), key=lambda s: (s.start, s.end, s.rule)))


def review_doctor_mask(
    text: str, spans: Sequence[Span], literals: Sequence[str]
) -> MaskReview:
    """原文 text に区間 spans を当てた後の、送られる文とまだ疑われる区間。"""
    source = apply_spans(text, spans)
    check = check_text(source)
    masked = check.masked
    detected = [Suspect(d.rule, d.start, d.end) for d in check.detections]
    if has_known_literal(source, literals):
        suspects = _ordered(detected + _literal_suspects(masked, literals))
        return MaskReview(masked, suspects, REASON_KNOWN_IDENTIFIER, False)
    if detected:
        return MaskReview(masked, _ordered(detected), detected[0].rule, True)
    if not masked.strip():
        return MaskReview(masked, (), None, False)
    found, located = _prompt_suspects(masked)
    if not found and located:
        return MaskReview(masked, (), None, False)
    reason = found[0].rule if found else "unlocated"
    return MaskReview(masked, _ordered(found), reason, located and bool(found))


def confirmed_mask(
    spans: Sequence[Span], review: MaskReview, *, confirmed: bool = True
) -> DoctorMask:
    """保存する DoctorMask。確かめた記録は今まだ疑われている区間ちょうどを許す。

    疑いが残っていない記録は確かめる語が無いので confirmed_clear=False にする。
    確かめて送れない（confirmable でない）記録を confirmed で渡すと ValueError。
    """
    text_spans = [TextSpan(start=s, end=e) for s, e in spans]
    if not confirmed or not review.suspects:
        return DoctorMask(spans=text_spans)
    if not review.confirmable:
        raise ValueError(
            "確かめて送れない記録（仮名ID・受付番号、位置の分からない疑い）"
        )
    allowed = [TextSpan(start=s.start, end=s.end) for s in review.suspects]
    return DoctorMask(spans=text_spans, confirmed_clear=True, allowed=allowed)

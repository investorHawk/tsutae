"""伏せ字（二段）。docs/architecture.md §5、docs/spec.md 13.2。

- 一次 `mask_text`: 置換（姓辞書＋敬称、電話・メール・住所、病院名）
- 二次 `detect_identifiers`: 一次の後の文に掛ける別の厳しい規則。該当した記録は
  Claude に送らない（`UnprocessedEntry(reason=<規則名>)`）
- `check_text`: 一次→二次をまとめる

検出漏れはゼロにできない（辞書にない1字の姓など）。症例は全て合成。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tsutae.masking.detect import (
    RULE_AT_MARK,
    RULE_BEFORE_FACILITY,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    RULES,
    Detection,
    detect_identifiers,
)
from tsutae.masking.replace import (
    GENERIC_MASK,
    HOSPITAL_MASK,
    NAME_MASK,
    MaskResult,
    mask_text,
)

__all__ = [
    "GENERIC_MASK",
    "HOSPITAL_MASK",
    "NAME_MASK",
    "RULES",
    "RULE_AT_MARK",
    "RULE_BEFORE_FACILITY",
    "RULE_LONG_DIGITS",
    "RULE_UNKNOWN_BEFORE_HONORIFIC",
    "Detection",
    "MaskCheck",
    "MaskResult",
    "check_text",
    "detect_identifiers",
    "mask_text",
]


@dataclass(frozen=True)
class MaskCheck:
    masked: str
    detections: list[Detection]
    counts: dict[str, int] = field(default_factory=dict)  # 一次の置換件数

    @property
    def flagged(self) -> bool:
        """二次に掛かった（Claude に送らない）か。"""
        return bool(self.detections)

    @property
    def reason(self) -> str | None:
        """最初に掛かった規則名（`UnprocessedEntry.reason` に使う）。無ければ None。"""
        return self.detections[0].rule if self.detections else None


def check_text(text: str) -> MaskCheck:
    """一次の置換をしてから、その結果に二次の検出を掛ける。"""
    result = mask_text(text)
    return MaskCheck(
        masked=result.masked,
        detections=detect_identifiers(result.masked),
        counts=dict(result.counts),
    )

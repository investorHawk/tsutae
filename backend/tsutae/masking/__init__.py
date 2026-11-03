"""伏せ字（二段）。docs/architecture.md §5、docs/spec.md 13.2。

- `normalize_text`: 改行を `\\n` に、タブを空白に揃え、他の制御文字・書式文字を消す
- 一次 `mask_text`: 置換（仮名ID、姓辞書＋敬称、電話・メール・住所、病院名）
- 二次 `detect_in_patient_text`: 一次の後の患者の文に掛ける別の厳しい規則（例外なし）。
  該当した記録は Claude に送らない（`UnprocessedEntry(reason=<規則名>)`）
- 二次 `detect_identifiers`: 依頼文全体（H1・convert②）用。JSON のエスケープを空白と
  みなし、Skill の版のキーの値の `@` だけを数えない
- `check_text`: 正規化→一次→二次（detect_in_patient_text）をまとめる

二次は一次より厳しく、迷ったら検出する（誤検知はその記録が院内画面 D6 に回るだけ、
見逃しは識別子が外に出る）。ただし一次の出力（○○さん・[病院]・[伏せ字]）と
続柄・職種・一般語の許可語（allow_words.txt）には反応しない。

規則は改行・空白をまたいで働く（磯鷲\\n南さん・架空 病院・みらい ちゃん）。例外は
改行の前が明示の許可語の形容詞・副詞（allow_words.txt。だるい・やっと 等と、その活用
だるく・きつかった）・助詞・活用の切れ目のときだけ（だるい\\n医院へ は検出しない）。
語尾の形だけでは許さない（みらい\\n病院は検出）。通常の空白にはこの例外を使わない。
仮名ID・受付番号のハイフン類の前後、電話番号の区切り、住所の構成要素の間の空白・改行は
字数を問わない（P - DEMO0001・A -\\n023・090    1234    5678・架空町 1 - 2）。

検出漏れはゼロにできない。分かっている例: 辞書にない1字の名前（孫の蓮くん）、
敬称の付かない名前（島医師・主治医の磯鷲・担当は磯鷲です・Dr.磯鷲・Mr.Isowashi・
isowashi-san）、施設語の付かない施設名（架空会で点滴）、空白の前の名前＋職種
（磯鷲 看護師さん）、許可語の形容詞と同じ綴りのひらがなの名前、ハイフン類の無い
仮名ID（P DEMO0001・PDEMO0001）、番地の無い住所（架空台）。症例は全て合成。

MaskResult・MaskCheck・Detection は frozen で、中身も書き換えられない（detections は
tuple、counts は読み取り専用の Mapping）。

モジュール: chars.py（文字の種類）、words.py（辞書・許可語の判定）、normalize.py
（正規化）、replace.py（一次）、detect.py・detect_honorific.py・detect_facility.py・
detect_address.py・detect_id.py（二次）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from tsutae.masking.detect import (
    RULE_ADDRESS_NUMBER,
    RULE_AT_MARK,
    RULE_BEFORE_FACILITY,
    RULE_ID_LIKE,
    RULE_LONG_DIGITS,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    RULES,
    Detection,
    detect_identifiers,
    detect_in_patient_text,
)
from tsutae.masking.normalize import normalize_text
from tsutae.masking.replace import (
    GENERIC_MASK,
    HOSPITAL_MASK,
    ID_MASK,
    NAME_MASK,
    MaskResult,
    mask_text,
)

__all__ = [
    "GENERIC_MASK",
    "HOSPITAL_MASK",
    "ID_MASK",
    "NAME_MASK",
    "RULES",
    "RULE_ADDRESS_NUMBER",
    "RULE_AT_MARK",
    "RULE_BEFORE_FACILITY",
    "RULE_ID_LIKE",
    "RULE_LONG_DIGITS",
    "RULE_UNKNOWN_BEFORE_HONORIFIC",
    "Detection",
    "MaskCheck",
    "MaskResult",
    "check_text",
    "detect_identifiers",
    "detect_in_patient_text",
    "mask_text",
    "normalize_text",
]


@dataclass(frozen=True)
class MaskCheck:
    masked: str
    detections: Sequence[Detection]  # tuple に直す
    counts: Mapping[str, int] = field(default_factory=dict)  # 一次の置換件数

    def __post_init__(self) -> None:
        # 入れ子も書き換えられないように、受け取った list・dict を写して固める
        object.__setattr__(self, "detections", tuple(self.detections))
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))

    @property
    def flagged(self) -> bool:
        """二次に掛かった（Claude に送らない）か。"""
        return bool(self.detections)

    @property
    def reason(self) -> str | None:
        """最初に掛かった規則名（`UnprocessedEntry.reason` に使う）。無ければ None。"""
        return self.detections[0].rule if self.detections else None


def check_text(text: str) -> MaskCheck:
    """正規化→一次の置換をしてから、その結果に二次の検出を掛ける（患者の文。例外なし）。

    masked と detections の位置は正規化の後の文のもの（改行は `\\n` で残る）。
    """
    result = mask_text(normalize_text(text))
    return MaskCheck(
        masked=result.masked,
        detections=detect_in_patient_text(result.masked),
        counts=result.counts,
    )

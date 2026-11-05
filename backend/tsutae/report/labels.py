"""レポートに出す短い表示名と、回答値の日本語（決まった文言だけ。AI の文は使わない）。"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from tsutae.schemas import Question

TEMPERATURE_ROW_KEY = "temperature"
TEMPERATURE_LABEL = "体温"

# 紙に出さない重さの判定語（spec 10・12.1）。AI が決める欄（用語名）に掛ける。
# 患者の原文（引用）には掛けない（患者が「重症」と書く自由がある）
SEVERITY_WORDS: tuple[str, ...] = (
    "Grade",
    "グレード",
    "軽症",
    "中等症",
    "重症",
    "重篤",
)

# 経過表の行・要確認で使う短い名前。Skill の質問文は長いので、既知の key だけ短くする。
# 未知の key（D4 で医師が足した質問など）は版の form の短い名前（`regimen.labels`）、
# それも無ければ質問文をそのまま使う
SHORT_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "numbness": "しびれ",
        "diarrhea": "下痢",
        "stomatitis": "口内炎",
        "nausea_appetite": "吐き気・食欲",
        "hand_foot": "手足の皮膚",
        "fever": TEMPERATURE_LABEL,
        TEMPERATURE_ROW_KEY: TEMPERATURE_LABEL,
    }
)

ANSWER_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "none": "なし",
        "present": "ある",
        "hard": "つらい",
        "not_measured": "測っていない",
        "measured": "測った",
    }
)


def question_label(
    key: str,
    questions: Sequence[Question],
    labels: Mapping[str, str] | None = None,
) -> str:
    """質問 key の表示名。

    既知の key は短い名前（SHORT_LABELS）、それ以外は版の form の短い名前（labels。
    v1.1）、それも無ければ質問文（旧 D4 で足した版など）、最後に key。
    """
    if key in SHORT_LABELS:
        return SHORT_LABELS[key]
    if labels and labels.get(key):
        return labels[key]
    for q in questions:
        if q.key == key:
            return q.text
    return key


def answer_label(value: str | None) -> str:
    if value is None:
        return ""
    return ANSWER_LABELS.get(value, value)


def has_severity_word(text: str) -> bool:
    """重さの判定語を含むか。全角・大文字小文字の違いは NFKC と小文字化でそろえる。"""
    folded = unicodedata.normalize("NFKC", text).lower()
    return any(
        unicodedata.normalize("NFKC", w).lower() in folded for w in SEVERITY_WORDS
    )

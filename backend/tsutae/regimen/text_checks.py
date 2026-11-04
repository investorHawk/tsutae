"""フォームの文の欄の検査（薬の量・H1・改行・「|」・YAML の読み戻し）と結果の型。

message に入力の文面は入れない（H1 に掛かった文をそのまま画面・ログに戻さない）。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import yaml

from tsutae.masking import detect_identifiers

# 薬の量: 数値＋量の単位、または AUC＋数値（NFKC の後に見る。mg/m²・ｍｇ も拾う）
_DOSE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|mcg|μg|µg|ug|g|ml|iu|単位|ミリグラム|グラム|ミリリットル|cc)"
    r"(?![a-z])|auc\s*=?\s*\d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FieldIssue:
    field_id: str
    code: str
    message: str


class RegimenFormError(ValueError):
    """フォームが描けない・採用できない。`issues` に欄の id と理由。"""

    def __init__(self, issues: Iterable[FieldIssue]) -> None:
        self.issues: tuple[FieldIssue, ...] = tuple(issues)
        super().__init__(
            "; ".join(f"{i.field_id}: {i.code}" for i in self.issues) or "invalid"
        )


# ---------------------------------------------------------------------------
# 文の欄
# ---------------------------------------------------------------------------


def has_dose(text: str) -> bool:
    """数値＋mg・mg/m²・mg/kg・g・mL・単位 等、または AUC＋数値を含むか。"""
    return _DOSE_RE.search(unicodedata.normalize("NFKC", text)) is not None


def yaml_same(fragment: str, expected: Any) -> bool:
    try:
        return yaml.safe_load(fragment) == expected
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        return False


# 制御文字（Cc）・見えない書式文字（Cf: ゼロ幅スペース・BOM・方向制御）・行と段落の区切り
# （Zl・Zp: U+2028/2029。str.splitlines と患者の画面で改行になる）
_CONTROL_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


def _control_chars(text: str, *, multiline: bool) -> bool:
    """改行以外の制御文字・見えない文字があるか。

    1行の欄の \\n・\\r は line_break で別に咎める。複数行の欄（補足の指示）は LF と
    タブだけ通す（CR は通さない。改行は LF にそろえて SKILL.md に CR を残さない）。
    """
    skip = "\n\t" if multiline else "\n\r"
    return any(
        unicodedata.category(ch) in _CONTROL_CATEGORIES and ch not in skip
        for ch in text
    )


def identifier_issue(field_id: str, value: str) -> FieldIssue | None:
    """H1 の検出（detect_identifiers）に掛かれば、規則の名前だけを持つ FieldIssue。"""
    rules = sorted({d.rule for d in detect_identifiers(value)})
    if not rules:
        return None
    return FieldIssue(
        field_id, "identifier", f"個人を特定しうる表現の疑い（{'・'.join(rules)}）"
    )


def yaml_issue(
    field_id: str, yaml_checks: Iterable[tuple[str, Any]]
) -> FieldIssue | None:
    """frontmatter に入れた形を YAML で読み戻して、どれか1つでも違えば FieldIssue。"""
    if all(yaml_same(fragment, expected) for fragment, expected in yaml_checks):
        return None
    return FieldIssue(
        field_id, "yaml", "SKILL.md の設定に入れると読み戻せない文字がある"
    )


def text_issues(
    field_id: str,
    value: str,
    *,
    max_len: int,
    multiline: bool = False,
    yaml_checks: Iterable[tuple[str, Any]] = (),
) -> Iterator[FieldIssue]:
    """1つの文の欄の検査。空の値は呼ぶ前に除く（必須は missing_fields）。"""
    if not multiline and ("\n" in value or "\r" in value):
        yield FieldIssue(field_id, "line_break", "改行を入れられない")
    if _control_chars(value, multiline=multiline):
        yield FieldIssue(field_id, "control", "制御文字を入れられない")
    if not multiline and "|" in value:
        yield FieldIssue(field_id, "pipe", "「|」を入れられない（表が崩れる）")
    if not multiline and value != value.strip():
        yield FieldIssue(field_id, "whitespace", "前後に空白を入れない")
    if len(value) > max_len:
        yield FieldIssue(field_id, "too_long", f"{max_len} 字までにする")
    if has_dose(value):
        yield FieldIssue(field_id, "dose", "薬の量（数値＋mg 等）は持たない")
    for issue in (identifier_issue(field_id, value), yaml_issue(field_id, yaml_checks)):
        if issue is not None:
            yield issue

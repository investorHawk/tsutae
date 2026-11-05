"""版の form の質問の短い名前（紙の経過表・医師画面の名前。v1.1、spec 9.1「質問の部品集」）。

- 既知の6問の名前は紙は `report.labels.SHORT_LABELS`、医師画面は画面の表が先に使う。
  ここが返すのは版の form の label（D4 で採用した版は regimen_forms、FOLFOX/CAPOX@1 は
  リポジトリの JSON）。form の無い版（旧 D4 の一文で上げた版など）は空
- SKILL.md を読み戻して解析はしない
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable

from tsutae.regimen.form import RegimenForm
from tsutae.regimen.source import form_from_skill

__all__ = ["labels_by_version", "question_labels_of", "version_labels"]

_VERSION_RE = re.compile(r"(?P<name>regimen-[a-z0-9-]+)@(?P<version>[1-9][0-9]{0,8})")


def question_labels_of(form: RegimenForm | None) -> dict[str, str]:
    """form の質問 key → 短い名前（key・label の無い行は入れない。form が無ければ空）。"""
    if form is None:
        return {}
    return {q.key: q.label for q in form.questions if q.key and q.label}


def version_labels(conn: sqlite3.Connection, skill_version: str) -> dict[str, str]:
    """`regimen-ram-wptx@1` の form の短い名前。regimen でない・形が違えば空。"""
    match = _VERSION_RE.fullmatch(skill_version)
    if match is None:
        return {}
    form = form_from_skill(conn, match["name"], int(match["version"]))
    return question_labels_of(form)


def labels_by_version(
    conn: sqlite3.Connection, versions: Iterable[str]
) -> dict[str, dict[str, str]]:
    """版ごとの短い名前（同じ版は1回だけ引く）。"""
    return {v: version_labels(conn, v) for v in sorted(set(versions))}

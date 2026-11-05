"""記録の版（`regimen-<識別名>@<版>`）の解決。skill_versions から引く（v1.1）。

- `questions_by_version(conn, versions=None)`: 版 → その版の質問集（経過表の未設問の判定）
- `regimen_skills_by_version(conn, versions)`: 版 → その版の RegimenSkill（保存した全文を
  検査して読む。記録ごとの用語 → 質問 key の対応に使う。spec 9.1）。登録の無い版・
  検査に通らない全文・frontmatter の版や種類が登録と違う全文は入れない（後の2つは
  版の文字列と型名だけを警告に残す）。入れなかった版の記録は prepare_input が安全側に
  倒す（どの用語も質問につなげない）
- regimen Skill は FOLFOX/CAPOX に限らない（`regimen-` で始まる正しい Skill 名）
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable

from tsutae import db
from tsutae.schemas import Question, RegimenSkill
from tsutae.skills import (
    REGIMEN_PREFIX,
    SkillValidationError,
    is_valid_skill_name,
    validate_skill_text,
)

__all__ = [
    "MAX_SCANNED_VERSIONS",
    "parse_version",
    "questions_by_version",
    "regimen_skills_by_version",
]

# questions_by_version(conn) が1つの Skill について順に引く版の上限（最新の版は別に必ず引く）
MAX_SCANNED_VERSIONS = 200
_VERSION_RE = re.compile(r"^(?P<name>[a-z0-9-]+)@(?P<version>[1-9][0-9]{0,8})$")
_log = logging.getLogger(__name__)


def _is_regimen_name(name: str) -> bool:
    """regimen Skill の名前か（FOLFOX/CAPOX に限らない。v1.1）。"""
    return is_valid_skill_name(name) and name.startswith(REGIMEN_PREFIX)


def parse_version(value: object) -> tuple[str, int] | None:
    """`"regimen-folfox@1"` → (名前, 版)。regimen Skill でない・形が違えば None。"""
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.fullmatch(value)
    if match is None or not _is_regimen_name(match["name"]):
        return None
    return match["name"], int(match["version"])


def _fetch_questions(
    conn: sqlite3.Connection, pairs: Iterable[tuple[str, int]]
) -> dict[str, list[Question]]:
    found: dict[str, list[Question]] = {}
    for name, version in sorted(set(pairs)):
        row = db.get_skill_version(conn, name, version)
        if row is not None and row["questions"] is not None:
            found[f"{name}@{version}"] = list(row["questions"])
    return found


def _scan_pairs(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """regimen Skill ごとに 1〜min(最新, 上限) の版と最新の版。"""
    pairs: list[tuple[str, int]] = []
    for name in db.list_skill_names(conn, REGIMEN_PREFIX):
        if not _is_regimen_name(name):
            continue
        latest = db.latest_skill_version(conn, name)
        if latest is None:
            continue
        top = int(latest["version"])
        if top > MAX_SCANNED_VERSIONS:
            _log.warning(
                "skill %s: 版 %d は MAX_SCANNED_VERSIONS を超える（途中は引かない）",
                name,
                top,
            )
        pairs.extend((name, v) for v in range(1, min(top, MAX_SCANNED_VERSIONS) + 1))
        pairs.append((name, top))
    return pairs


def questions_by_version(
    conn: sqlite3.Connection, versions: Iterable[str] | None = None
) -> dict[str, list[Question]]:
    """`"regimen-folfox@1"` → その版の質問集（regimen Skill の登録済みの版）。

    versions を渡せば、その版だけを引く（形の違う値・regimen でない Skill は無視）。
    渡さなければ skill_versions にある regimen Skill（FOLFOX/CAPOX に限らない）ごとに
    1〜min(最新, MAX_SCANNED_VERSIONS) と最新の版を引く
    （db に版の一覧を返す公開関数が無いための上限）。
    """
    if versions is None:
        return _fetch_questions(conn, _scan_pairs(conn))
    parsed = (parse_version(v) for v in versions)
    return _fetch_questions(conn, (p for p in parsed if p is not None))


def regimen_skills_by_version(
    conn: sqlite3.Connection, versions: Iterable[str]
) -> dict[str, RegimenSkill]:
    """`"regimen-ram-wptx@1"` → その版の RegimenSkill（skill_versions に保存した全文）。"""
    found: dict[str, RegimenSkill] = {}
    for name, version in sorted({p for v in versions if (p := parse_version(v))}):
        row = db.get_skill_version(conn, name, version)
        if row is None:
            continue
        key = f"{name}@{version}"
        try:
            skill = validate_skill_text(name, row["content"])
        except SkillValidationError as exc:
            _log.warning("skill %s の全文を読めない: %s", key, type(exc).__name__)
            continue
        if not isinstance(skill, RegimenSkill) or skill.version != version:
            _log.warning("skill %s の全文の版・種類が登録と違う", key)
            continue
        found[key] = skill
    return found

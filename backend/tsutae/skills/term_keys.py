"""用語 → 質問 key の対応（v1.1。版ごと。architecture 9c「用語と質問の対応」）。

- 全体の対応は ctcae_terms.json（32語）
- 版の対応は RegimenSkill の `term_keys`（全体の対応と違うものだけ。null も上書き）
- `term_keys_for(版の term_keys)` = 全体 ＋ 版の上書き。FOLFOX/CAPOX@1 は term_keys が
  無いので全体の対応のまま（評価済みの依頼文が変わらない）
- `asked_term_keys`: その版の質問に無い key は null（checks・紙の照合で同じ規則）
- `entry_term_keys(prepared, entry_no)`: その記録の版（Entry.skill_version）の対応
  （spec 9.1）。入力の版と違う版は PreparedInput.other_versions の材料。材料を引けなかった
  版は空の材料（`version_materials`）で全ての用語が null（○ を付けない側に倒す）。
  版の無い記録・材料の欠けは report の gate が entry_mismatch・skill_mismatch で止める
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from tsutae.schemas import PreparedInput, RegimenSkill, VersionTermKeys
from tsutae.synthetic import load_terms, term_question_keys

__all__ = [
    "asked_term_keys",
    "entry_term_keys",
    "global_term_keys",
    "input_term_keys",
    "record_versions",
    "term_keys_for",
]


@lru_cache(maxsize=1)
def _global() -> Mapping[str, str | None]:
    return MappingProxyType(term_question_keys(load_terms()))


def global_term_keys() -> dict[str, str | None]:
    """ctcae_terms.json の全体の対応（新しい dict）。"""
    return dict(_global())


def term_keys_for(
    overrides: Mapping[str, str | None] | None,
    terms: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, str | None]:
    """全体の対応（terms。既定は ctcae_terms.json）に版の term_keys を重ねた対応。

    版の term_keys にあって一覧に無い用語は足さない（用語の一覧は変えない）。
    """
    base = dict(_global()) if terms is None else term_question_keys(terms)
    extra = overrides or {}
    return {term: extra.get(term, key) for term, key in base.items()}


def asked_term_keys(
    overrides: Mapping[str, str | None] | None,
    asked: Iterable[str],
    terms: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, str | None]:
    """term_keys_for のうち、その版の質問（asked）に無い key を null にした対応。"""
    keys = frozenset(asked)
    return {
        term: (key if key in keys else None)
        for term, key in term_keys_for(overrides, terms).items()
    }


def input_term_keys(
    prepared: PreparedInput, terms: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, str | None]:
    """変換の入力の版（今の版）の対応。入力の質問に無い key は null。"""
    asked = [q.key for q in prepared.input.questions]
    return asked_term_keys(prepared.term_keys, asked, terms)


def entry_term_keys(
    prepared: PreparedInput,
    entry_no: int,
    terms: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, str | None]:
    """その記録の版の対応（全体 ＋ その版の term_keys。その版の質問に無い key は null）。"""
    version = prepared.entry_versions.get(entry_no)
    other = prepared.other_versions.get(version) if version is not None else None
    if other is None:
        return input_term_keys(prepared, terms)
    return asked_term_keys(other.term_keys, other.question_keys, terms)


def record_versions(
    entry_versions: Mapping[int, str],
    regimen_skill: RegimenSkill,
    version_skills: Mapping[str, RegimenSkill] | None,
) -> dict[str, VersionTermKeys]:
    """送る記録の版のうち、入力の版と違い材料（その版の RegimenSkill）のあるものの対応の材料。"""
    found: dict[str, VersionTermKeys] = {}
    for version in sorted(set(entry_versions.values())):
        skill = (version_skills or {}).get(version)
        if version == regimen_skill.skill_version or skill is None:
            continue
        found[version] = VersionTermKeys(
            term_keys=dict(skill.term_keys or {}),
            question_keys=[q.key for q in skill.questions],
        )
    return found

"""薬の名前の候補（D4 レジメンの左の欄の入力候補・チャットの札。spec §16）。

- 採用済みのレジメン（`GET /regimens` と同じ。置かれていて検査に通り、skill_versions に版が
  ある。並びも同じで FOLFOX・CAPOX が先）の今の版の form の薬 → 固定の5つの順。重複は除く
- form の無い版（旧 D4 の一文で上げた版）は飛ばす。読めない form も警告だけで飛ばす（候補は
  入力の補助なので、壊れた版があっても画面を止めない。`skills.catalog` と同じ扱い）
- 名前だけを扱う。薬の量・経路は持たない
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from tsutae import db
from tsutae.regimen.source import form_from_skill
from tsutae.skills import list_regimens

__all__ = ["PLAN_DRUG_NAMES", "merge_drug_names", "regimen_drug_names"]

_log = logging.getLogger(__name__)

# docs/plan-d4-regimen.md §5 のレジメンの薬（まだ採用していなくても候補に出す）
PLAN_DRUG_NAMES = (
    "パクリタキセル",
    "ラムシルマブ",
    "ベバシズマブ",
    "イリノテカン",
    "トリフルリジン・チピラシル",
)


def merge_drug_names(adopted: Iterable[str | None], fixed: Iterable[str]) -> list[str]:
    """採用済み → 固定の順に、前後の空白を除いて並べる（空は除く。同じ名前は最初の1回だけ）。"""
    cleaned = ((name or "").strip() for group in (adopted, fixed) for name in group)
    return list(dict.fromkeys(name for name in cleaned if name))


def _form_drug_names(
    conn: sqlite3.Connection, skill_name: str, version: int
) -> list[str | None]:
    try:
        form = form_from_skill(conn, skill_name, version)
    except (OSError, ValueError) as exc:  # pydantic の ValidationError は ValueError
        # 中身（form の文面）は記録に残さない
        _log.warning(
            "form を読めないので薬の候補から外す: %s@%d（%s）",
            skill_name,
            version,
            type(exc).__name__,
        )
        return []
    return [] if form is None else [drug.name for drug in form.drugs]


def regimen_drug_names(conn: sqlite3.Connection, skills_dir: Path) -> list[str]:
    """採用済みのレジメンの薬と固定の5つの名前（並びは決まっている）。"""
    adopted: list[str | None] = []
    for regimen in list_regimens(skills_dir):
        latest = db.latest_skill_version(conn, regimen.skill_name)
        if latest is not None:
            adopted += _form_drug_names(conn, regimen.skill_name, latest["version"])
    return merge_drug_names(adopted, PLAN_DRUG_NAMES)

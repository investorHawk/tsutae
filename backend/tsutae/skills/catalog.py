"""置かれているレジメンの一覧（v1.1。architecture 9c「レジメンの一覧（T95）」）。

- `list_regimens(skills_dir)`: skills_dir 直下の `regimen-*/SKILL.md` を検査して読み、
  識別名・Skill 名・版・表示名（frontmatter の display_name、無ければ識別名）を返す。
  並びは評価済みの2つ（FOLFOX・CAPOX）を先に、ほかは識別名の順
- 壊れた SKILL.md・読めないフォルダは載せない（名前と code だけを警告に残す。患者の登録や
  医師画面を1つの壊れた Skill で止めない。`GET /skills` の invalid と同じ考え）
- 名前と regimen の対応（`regimen-` + 識別名の小文字）は `validate_skill_text` が検査する
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from tsutae.schemas import RegimenSkill
from tsutae.skills.loader import (
    REGIMEN_SKILL_NAMES,
    SKILL_FILE_NAME,
    SkillValidationError,
    is_valid_skill_name,
    load_skill,
)

__all__ = ["REGIMEN_PREFIX", "RegimenInfo", "list_regimens", "regimen_codes"]

REGIMEN_PREFIX = "regimen-"
_BUILTIN_ORDER = tuple(REGIMEN_SKILL_NAMES)  # FOLFOX, CAPOX
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegimenInfo:
    """一覧の1件。display_name は紙のヘッダ・医師画面の名前。"""

    code: str
    skill_name: str
    version: int
    display_name: str


def _order(info: RegimenInfo) -> tuple[int, str]:
    if info.code in _BUILTIN_ORDER:
        return _BUILTIN_ORDER.index(info.code), ""
    return len(_BUILTIN_ORDER), info.code


def _candidates(root: Path) -> list[str]:
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name)
    except FileNotFoundError:
        return []
    return [
        p.name
        for p in children
        if p.name.startswith(REGIMEN_PREFIX)
        and is_valid_skill_name(p.name)
        and (p / SKILL_FILE_NAME).is_file()
    ]


def _info(name: str, root: Path) -> RegimenInfo | None:
    try:
        skill = load_skill(name, root)
    except (SkillValidationError, OSError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        _log.warning("regimen %s を一覧に載せない: %s", name, code)
        return None
    if not isinstance(skill, RegimenSkill):  # 接頭辞で決まるので通常は起きない
        return None
    return RegimenInfo(
        code=skill.regimen,
        skill_name=skill.name,
        version=skill.version,
        display_name=skill.display_name or skill.regimen,
    )


def list_regimens(skills_dir: Path) -> list[RegimenInfo]:
    """置かれていて検査に通るレジメン（skills_dir が無ければ空）。"""
    root = Path(skills_dir)
    found = (_info(name, root) for name in _candidates(root))
    return sorted((i for i in found if i is not None), key=_order)


def regimen_codes(skills_dir: Path) -> frozenset[str]:
    """置かれているレジメンの識別名（患者の登録の照合に使う）。"""
    return frozenset(i.code for i in list_regimens(skills_dir))

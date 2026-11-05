"""load_regimen_skill が FOLFOX/CAPOX 以外の識別名も読める（T93。D4 で採用したレジメン）。

- 識別名 → `regimen-<小文字>`（FOLFOX・CAPOX は今の対応のまま）
- 置かれていない・書式の違う識別名は unknown_regimen（今の XELOX のテストと同じ）
"""

from __future__ import annotations

from pathlib import Path

import pytest
from regimen_fixtures import extra_form

from tsutae.regimen import render_regimen_skill
from tsutae.skills import SkillValidationError, load_regimen_skill


def _place(skills_dir: Path, name: str, text: str) -> None:
    (skills_dir / name).mkdir(parents=True)
    (skills_dir / name / "SKILL.md").write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("fixture", "code", "name"),
    [
        ("folfiri_bv", "FOLFIRI-BV", "regimen-folfiri-bv"),
        ("ram_wptx", "RAM-WPTX", "regimen-ram-wptx"),
        ("lonsurf_bv", "LONSURF-BV", "regimen-lonsurf-bv"),
    ],
)
def test_adopted_regimen_is_loadable(
    tmp_path: Path, fixture: str, code: str, name: str
) -> None:
    _place(tmp_path, name, render_regimen_skill(extra_form(fixture), 1))
    skill = load_regimen_skill(code, skills_dir=tmp_path)
    assert skill.name == name and skill.regimen == code and skill.version == 1


@pytest.mark.parametrize("code", ["FOLFIRI-BV", "folfiri-bv", "../x", "", "A" * 31])
def test_missing_or_bad_code_is_unknown(tmp_path: Path, code: str) -> None:
    with pytest.raises(SkillValidationError) as exc:
        load_regimen_skill(code, skills_dir=tmp_path)
    assert exc.value.code == "unknown_regimen"


def test_name_and_regimen_must_agree(tmp_path: Path) -> None:
    text = render_regimen_skill(extra_form("folfiri_bv"), 1)
    _place(
        tmp_path,
        "regimen-folfiri-bv",
        text.replace("regimen: FOLFIRI-BV", "regimen: RAM-WPTX"),
    )
    with pytest.raises(SkillValidationError) as exc:
        load_regimen_skill("FOLFIRI-BV", skills_dir=tmp_path)
    assert exc.value.code == "regimen_mismatch"

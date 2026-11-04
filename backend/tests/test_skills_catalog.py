"""T95: レジメンの一覧（`list_regimens`）と、Skill 名と regimen の食い違いの検査。

- 一覧は skills_dir の `regimen-*` の frontmatter から 識別名・Skill 名・版・表示名
  （display_name、無ければ識別名）。FOLFOX・CAPOX を先に、ほかは識別名の順
- 壊れた SKILL.md・SKILL.md の無いフォルダ・report-format は載せない（患者の登録を止めない）
- 全ての `regimen-*` で name == 'regimen-' + regimen の小文字（T91 の検証の指摘）
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from regimen_fixtures import extra_form

from tsutae.config import SKILLS_DIR
from tsutae.regimen import render_regimen_skill
from tsutae.skills import (
    RegimenInfo,
    SkillValidationError,
    list_regimens,
    regimen_codes,
    validate_skill_text,
)


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    dst = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, dst)
    return dst


def _place(skills_dir: Path, name: str, text: str) -> None:
    (skills_dir / name).mkdir(parents=True)
    (skills_dir / name / "SKILL.md").write_text(text, encoding="utf-8")


def test_builtin_regimens() -> None:
    assert list_regimens(SKILLS_DIR) == [
        RegimenInfo("FOLFOX", "regimen-folfox", 1, "FOLFOX"),
        RegimenInfo("CAPOX", "regimen-capox", 1, "CAPOX"),
    ]
    assert regimen_codes(SKILLS_DIR) == frozenset({"FOLFOX", "CAPOX"})


def test_adopted_regimens_are_listed_with_display_name(skills_dir: Path) -> None:
    _place(
        skills_dir, "regimen-ram-wptx", render_regimen_skill(extra_form("ram_wptx"), 3)
    )
    _place(
        skills_dir,
        "regimen-folfiri-bv",
        render_regimen_skill(extra_form("folfiri_bv"), 1),
    )
    assert [r.code for r in list_regimens(skills_dir)] == [
        "FOLFOX",
        "CAPOX",
        "FOLFIRI-BV",
        "RAM-WPTX",
    ]
    ram = next(r for r in list_regimens(skills_dir) if r.code == "RAM-WPTX")
    assert ram == RegimenInfo("RAM-WPTX", "regimen-ram-wptx", 3, "RAM＋wPTX")


def test_broken_and_other_skills_are_not_listed(skills_dir: Path) -> None:
    _place(skills_dir, "regimen-broken", "---\nname: regimen-broken\n")
    (skills_dir / "regimen-empty").mkdir()
    (skills_dir / "regimen-file").write_text("x", encoding="utf-8")
    (skills_dir / "Regimen-UPPER").mkdir()
    assert [r.code for r in list_regimens(skills_dir)] == ["FOLFOX", "CAPOX"]


def test_missing_skills_dir_is_empty(tmp_path: Path) -> None:
    assert list_regimens(tmp_path / "nope") == []


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("regimen-ram-wptx", "FOLFOX"),  # 既知の識別名を別の名前のフォルダに
        ("regimen-ram-wptx", "RAM-WPTX2"),
        ("regimen-ram-wptx", "FOLFIRI-BV"),
    ],
)
def test_name_must_be_regimen_dash_lower_code(name: str, code: str) -> None:
    text = render_regimen_skill(extra_form("ram_wptx"), 1)
    text = text.replace("regimen: RAM-WPTX", f"regimen: {code}")
    with pytest.raises(SkillValidationError) as exc:
        validate_skill_text(name, text)
    assert exc.value.code == "regimen_mismatch"


def test_mismatched_skill_is_not_listed(skills_dir: Path) -> None:
    text = render_regimen_skill(extra_form("ram_wptx"), 1)
    _place(
        skills_dir, "regimen-ram-wptx", text.replace("regimen: RAM-WPTX", "regimen: X")
    )
    assert [r.code for r in list_regimens(skills_dir)] == ["FOLFOX", "CAPOX"]

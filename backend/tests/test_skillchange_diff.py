"""tsutae.skillchange.diff（unified diff と frontmatter の version の書き換え）。"""

from __future__ import annotations

import pytest

from tsutae.skillchange.diff import set_version, unified
from tsutae.skillchange.errors import SkillChangeError

TEXT = "---\nname: regimen-x\nversion: 1\nregimen: FOLFOX\n---\n\n# 本文\nversion: 9\n"


def test_unified_is_empty_when_equal() -> None:
    assert unified(TEXT, TEXT) == ""


def test_unified_shows_removed_and_added_lines() -> None:
    new = TEXT.replace("# 本文", "# 本文（改）")
    diff = unified(old=TEXT, new=new)
    assert diff.startswith("--- a/SKILL.md\n+++ b/SKILL.md\n@@")
    assert "\n-# 本文\n" in diff
    assert "\n+# 本文（改）\n" in diff


def test_unified_uses_given_path_in_headers() -> None:
    diff = unified(TEXT, TEXT + "x\n", path="regimen-x/SKILL.md")
    assert diff.startswith("--- a/regimen-x/SKILL.md\n+++ b/regimen-x/SKILL.md\n")


def test_unified_marks_missing_final_newline() -> None:
    diff = unified("a\nb\n", "a\nc")
    assert "+c\n\\ No newline at end of file\n" in diff
    assert diff.endswith("\n")


def test_set_version_changes_only_frontmatter_line() -> None:
    new = set_version(TEXT, 2)
    assert new == TEXT.replace("version: 1\n", "version: 2\n", 1)
    assert "version: 9" in new  # 本文の同じ形の行は触らない


def test_set_version_keeps_crlf_and_bom() -> None:
    text = "﻿" + TEXT.replace("\n", "\r\n")
    new = set_version(text, 3)
    assert new.startswith("﻿---\r\n")
    assert "\r\nversion: 3\r\n" in new
    assert new.count("\r\n") == text.count("\r\n")


def test_set_version_replaces_value_with_comment() -> None:
    text = TEXT.replace("version: 1", "version:   1   # 版")
    assert "\nversion: 5\n" in set_version(text, 5)


def test_set_version_does_not_mutate_argument() -> None:
    original = str(TEXT)
    set_version(TEXT, 2)
    assert original == TEXT


@pytest.mark.parametrize(
    "text",
    [
        "---\nname: regimen-x\n---\n",  # version が無い
        "---\nname: regimen-x\nversion: 1\nversion: 2\n---\n",  # 2つある
        "name: regimen-x\nversion: 1\n",  # frontmatter が無い
        "---\nname: regimen-x\nversion: 1\n",  # 閉じていない
        "---\nmeta:\n  version: 1\n---\n",  # 入れ子だけ
    ],
)
def test_set_version_rejects_unexpected_shapes(text: str) -> None:
    with pytest.raises(SkillChangeError) as info:
        set_version(text, 2)
    assert info.value.code == "version_line"


@pytest.mark.parametrize("version", [0, -1, True, "2"])
def test_set_version_rejects_bad_version(version: object) -> None:
    with pytest.raises(ValueError):
        set_version(TEXT, version)  # type: ignore[arg-type]


def test_unified_splits_only_on_newline() -> None:
    old = "a b\nc\n"
    diff = unified(old, "a b\nd\n")
    assert " a b\n" in diff
    assert "No newline" not in diff

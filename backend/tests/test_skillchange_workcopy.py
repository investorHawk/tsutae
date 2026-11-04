"""tsutae.skillchange.workcopy（作業コピーの場所と、その1ファイルだけを許す H3）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tsutae.pipeline.logs import MemoryLogger
from tsutae.skillchange.workcopy import (
    make_work_copy_h3,
    relative_work_copy_path,
    work_copy_path,
)

NAME = "regimen-folfox"


@pytest.fixture
def work_root(tmp_path: Path) -> Path:
    root = (tmp_path / "work").resolve()
    path = work_copy_path(root, NAME)
    path.parent.mkdir(parents=True)
    path.write_text("x", "utf-8")
    return root


def _write(path: str | Path | None, tool: str = "Write") -> dict[str, Any]:
    tool_input = {"content": "x"} if path is None else {"file_path": str(path)}
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def _denied(result: dict) -> bool:
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


# ---------------------------------------------------------------------------
# 場所
# ---------------------------------------------------------------------------


def test_work_copy_is_not_under_dot_claude(tmp_path: Path) -> None:
    """回帰: CLI は .claude/ の下への書き込みを acceptEdits でも保護する。"""
    path = work_copy_path(tmp_path, NAME)
    assert "/.claude/" not in str(path)
    assert not any(part.startswith(".") for part in path.relative_to(tmp_path).parts)
    assert path == tmp_path / "skills" / NAME / "SKILL.md"
    assert relative_work_copy_path(NAME) == f"skills/{NAME}/SKILL.md"


@pytest.mark.parametrize("bad", ["evil", "../regimen-folfox", "regimen-a/b", ""])
def test_work_copy_path_rejects_bad_names(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        work_copy_path(tmp_path, bad)


# ---------------------------------------------------------------------------
# H3
# ---------------------------------------------------------------------------


async def test_h3_allows_only_the_work_copy(work_root: Path) -> None:
    logger = MemoryLogger()
    h3 = make_work_copy_h3(work_root, NAME, logger)
    target = work_copy_path(work_root, NAME)
    for tool in ("Write", "Edit", "MultiEdit"):
        assert await h3(_write(target, tool), None, None) == {}
    assert [r["tool_name"] for r in logger.find("hook_h3_allow")] == [
        "Write",
        "Edit",
        "MultiEdit",
    ]
    assert {r["hook_name"] for r in logger.records} == {"H3"}


async def test_h3_denies_other_paths(work_root: Path) -> None:
    logger = MemoryLogger()
    h3 = make_work_copy_h3(work_root, NAME, logger)
    skills = work_root / "skills"
    bad = [
        work_root / ".claude" / "skills" / NAME / "SKILL.md",  # 旧い配置
        skills / "regimen-capox" / "SKILL.md",  # 別の Skill 名（新規作成も）
        skills / "report-format-default" / "SKILL.md",
        skills / NAME / "README.md",
        skills / NAME / "sub" / "SKILL.md",
        skills / NAME / ".." / ".." / "skills" / "x" / "SKILL.md",
        skills / NAME / ".." / ".." / ".." / "SKILL.md",
        skills / "SKILL.md",
        work_root / "SKILL.md",
        Path("/etc/passwd"),
        Path("skills") / NAME / "SKILL.md",  # 相対パス
        None,
    ]
    for path in bad:
        result = await h3(_write(path), None, None)
        assert _denied(result), path
    assert len(logger.find("hook_h3_deny")) == len(bad)
    reason = result["hookSpecificOutput"]["permissionDecisionReason"]
    assert f"skills/{NAME}/SKILL.md" in reason
    assert "/.claude/" not in reason


async def test_h3_allows_dotdot_that_resolves_to_target(work_root: Path) -> None:
    h3 = make_work_copy_h3(work_root, NAME, MemoryLogger())
    path = work_root / "skills" / NAME / ".." / NAME / "SKILL.md"
    assert await h3(_write(path), None, None) == {}


async def test_h3_denies_symlinked_copy(work_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("x", "utf-8")
    target = work_copy_path(work_root, NAME)
    target.unlink()
    os.symlink(outside / "SKILL.md", target)
    h3 = make_work_copy_h3(work_root, NAME, MemoryLogger())
    assert _denied(await h3(_write(target), None, None))


async def test_h3_denies_symlinked_skill_dir(work_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("x", "utf-8")
    skill_dir = work_copy_path(work_root, NAME).parent
    (skill_dir / "SKILL.md").unlink()
    skill_dir.rmdir()
    os.symlink(outside, skill_dir)
    h3 = make_work_copy_h3(work_root, NAME, MemoryLogger())
    assert _denied(await h3(_write(work_copy_path(work_root, NAME)), None, None))


async def test_h3_ignores_other_tools(work_root: Path) -> None:
    logger = MemoryLogger()
    h3 = make_work_copy_h3(work_root, NAME, logger)
    assert await h3(_write(work_root / "x", "Read"), None, None) == {}
    assert await h3("not a dict", None, None) == {}
    assert logger.records == []


def test_h3_rejects_bad_skill_name(work_root: Path) -> None:
    with pytest.raises(ValueError):
        make_work_copy_h3(work_root, "../x", MemoryLogger())

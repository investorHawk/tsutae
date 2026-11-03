"""書き換え用の作業コピーの場所と、その1ファイルだけに書き込みを限る H3。

作業コピーは `<work_root>/skills/<skill_name>/SKILL.md`（`.claude/` の下に置かない）。
Claude Code の CLI は `.claude/` の下への書き込みを保護していて、
permission_mode="acceptEdits" でも許可を求める（サーバーには許可を出す人がいないので
拒否され、書き換えが no_change で終わる）。作業ディレクトリ（cwd=work_root）の中の
ドットで始まらない場所なら acceptEdits で通る。

場所を決めるのは `work_copy_path` だけ（service・editor・check・偽の editor が使う）。

H3（`make_work_copy_h3`）: Write / Edit / MultiEdit の file_path を resolve した結果が、
作業コピーの SKILL.md ちょうど1つと一致する時だけ通す。相対パス・`..`・シンボリック
リンク・別の Skill 名・`.claude/skills/...` は deny。ログは pipeline の H3 と同じ
`hook_h3_allow` / `hook_h3_deny`（hook_name="H3"。文面は入れない）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from tsutae.pipeline.hooks import H3_MATCHER
from tsutae.pipeline.logs import EventLogger, reason_code
from tsutae.skills import SKILL_FILE_NAME, is_valid_skill_name

__all__ = [
    "WORK_SKILLS_DIR",
    "make_work_copy_h3",
    "relative_work_copy_path",
    "work_copy_path",
]

HookFn = Callable[[Any, str | None, Any], Awaitable[dict[str, Any]]]

# work_root の下の、作業コピーを置くディレクトリ（ドットで始めない）
WORK_SKILLS_DIR = "skills"


def relative_work_copy_path(skill_name: str) -> str:
    """作業ディレクトリからの相対パス（`skills/<skill_name>/SKILL.md`）。"""
    if not is_valid_skill_name(skill_name):
        raise ValueError("Skill 名の書式が違う")
    return f"{WORK_SKILLS_DIR}/{skill_name}/{SKILL_FILE_NAME}"


def work_copy_path(work_root: Path, skill_name: str) -> Path:
    """作業コピーの SKILL.md の場所（`<work_root>/skills/<skill_name>/SKILL.md`）。"""
    return Path(work_root) / relative_work_copy_path(skill_name)


def _get(data: Any, key: str) -> Any:
    return data.get(key) if isinstance(data, dict) else None


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _write_problem(file_path: Any, target: Path) -> str | None:
    if not isinstance(file_path, str) or not file_path:
        return "no_file_path"
    path = Path(file_path)
    if not path.is_absolute():
        return "not_absolute"
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return "unresolvable"
    return None if resolved == target else "outside_work_copy"


def make_work_copy_h3(work_root: Path, skill_name: str, logger: EventLogger) -> HookFn:
    """書き込みを作業コピーの SKILL.md（resolve 後）ちょうど1つに限る H3。

    target は work_root だけを resolve して組み立てる（作業コピーやその親が
    シンボリックリンクにすり替わっていれば、resolve した file_path と一致しない）。
    """
    target = work_copy_path(Path(work_root).resolve(), skill_name)
    reason = (
        f"書き込めるのは {target}（作業ディレクトリの "
        f"{relative_work_copy_path(skill_name)}）だけ。file_path はこの絶対パスにする"
    )

    async def h3(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
        tool_name = _get(input_data, "tool_name")
        if tool_name not in H3_MATCHER.split("|"):
            return {}
        code = _write_problem(_get(_get(input_data, "tool_input"), "file_path"), target)
        fields = {"tool_name": tool_name, "agent_type": _get(input_data, "agent_type")}
        if code is None:
            logger.event("hook_h3_allow", hook_name="H3", decision="allow", **fields)
            return {}
        logger.event(
            "hook_h3_deny", hook_name="H3", decision=reason_code("deny", code), **fields
        )
        return _deny(reason)

    return h3

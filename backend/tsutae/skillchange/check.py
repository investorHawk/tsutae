"""書き換えの後の検査（PostToolUse の Hook）。docs/architecture.md §9b。

エージェントが写しの SKILL.md を Write / Edit した直後に、request_change が後で掛ける
検査（`validate_skill_text`・version が元のまま・承認で version 行を上げられる）と
同じ合否を先に見て、通らなければ「どの項目が・どう違うか」をモデルに返して直させる。

- 返し方: `decision: "block"` と `reason`、`hookSpecificOutput.additionalContext`
  （PostToolUse。ツールはもう動いているので止めはしない。理由をモデルに渡すだけ）。
  `continue` は触らない（False にすると run 全体が止まる）。通れば `{}`
- 理由に載せるのは項目の位置と規則（pydantic のエラーは入力値を含めない形）
- ログは `hook_skill_check_allow` / `hook_skill_check_retry`（decision は
  `retry:<規則のコード>`）。文面は入れない
- Hook の中で例外を出さない（on_failure="block" で書き換え全体が止まる）
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsutae.pipeline.hooks import H3_MATCHER
from tsutae.pipeline.logs import EventLogger, reason_code
from tsutae.schemas import QUESTION_KEY_PATTERN, RegimenSkill
from tsutae.skillchange.diff import set_version
from tsutae.skillchange.errors import SkillChangeError
from tsutae.skills import (
    MAX_SKILL_CHARS,
    SKILL_FILE_NAME,
    SkillValidationError,
    is_valid_skill_name,
    validate_skill_text,
)

__all__ = [
    "SKILL_CHECK_MATCHER",
    "Baseline",
    "baseline_of",
    "check_skill_text",
    "make_skill_check",
    "read_baseline",
]

HookFn = Callable[[Any, str | None, Any], Awaitable[dict[str, Any]]]
Problem = tuple[str, str]  # (規則のコード, モデルへの理由)

SKILL_CHECK_MATCHER = H3_MATCHER  # "Write|Edit|MultiEdit"
HOOK_NAME = "skill_check"
_HEAD = (
    "書き換えた {path} はアプリの検査に通らない（このままでは承認に出せない）。"
    "Read で読み直し、下の点を Edit で直す（直すと、もう一度検査される）: "
)
_REGIMEN_RULES = (
    "questions の各項目は key・text・answer_type の3つ。key は "
    f"{QUESTION_KEY_PATTERN} に合わせ、重複させない。answer_type は three_level か"
    " temperature のどちらか。fixed_rules の question_key は questions にある"
    " temperature の質問の key、threshold_celsius は 35.0〜42.0。"
    "pump_removal_day は 1 以上 cycle_days 以下"
)
_REPORT_RULES = (
    "sections は header・attention・grid・per_symptom・quotes から選ぶ。"
    "quotes_max_items は 0〜200、low_confidence_threshold は 0〜1、"
    "fever_attention_celsius は 35.0〜42.0"
)


@dataclass(frozen=True)
class Baseline:
    """書き換える前の Skill（元の版と、regimen Skill なら今の質問の key）。"""

    version: int | None
    question_keys: tuple[str, ...] = ()


def baseline_of(skill_name: str, text: str) -> Baseline:
    """検査に通らない本文なら Baseline(None, ())（版を比べない）。"""
    try:
        skill = validate_skill_text(skill_name, text)
    except SkillValidationError:
        return Baseline(None)
    keys = (
        tuple(q.key for q in skill.questions) if isinstance(skill, RegimenSkill) else ()
    )
    return Baseline(skill.version, keys)


def _skill_file(work_root: Path, skill_name: str) -> Path:
    return Path(work_root) / ".claude" / "skills" / skill_name / SKILL_FILE_NAME


def read_baseline(work_root: Path, skill_name: str) -> Baseline:
    """editor を回す前の写しを読む（読めなければ Baseline(None, ())）。"""
    if not is_valid_skill_name(skill_name):
        return Baseline(None)
    try:
        text = _skill_file(work_root, skill_name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return Baseline(None)
    return baseline_of(skill_name, text)


# ---------------------------------------------------------------------------
# 検査（純関数）
# ---------------------------------------------------------------------------


def _rules_for(skill_name: str) -> str:
    return _REGIMEN_RULES if skill_name.startswith("regimen-") else _REPORT_RULES


def _validation_reason(skill_name: str, exc: SkillValidationError) -> str:
    detail = exc.message
    if exc.code == "format":
        return (
            f"frontmatter が YAML として読めない（{detail}）。最初の行と frontmatter の"
            "終わりを --- にし、キーを重複させず、{key: ..., text: ...} の形を保つ"
        )
    if exc.code == "name_mismatch":
        return f"name は {skill_name} のまま変えない"
    if exc.code == "regimen_mismatch":
        return "regimen は変えない"
    if exc.code == "too_large":
        return f"SKILL.md 全体を {MAX_SKILL_CHARS} 字以内にする"
    if exc.code == "schema":
        return f"frontmatter の項目が決まりに合わない（{detail}）。決まり: " + (
            _rules_for(skill_name)
        )
    return f"検査に通らない（{exc.code}）"


def check_skill_text(
    skill_name: str, text: str, base_version: int | None
) -> Problem | None:
    """request_change と同じ合否。通れば None、通らなければ (コード, 理由)。"""
    try:
        skill = validate_skill_text(skill_name, text)
    except SkillValidationError as exc:
        return exc.code, _validation_reason(skill_name, exc)
    if base_version is not None and skill.version != base_version:
        return "version_changed", (
            f"version は {base_version} のまま変えない（版は承認の時にアプリが上げる）"
        )
    try:
        set_version(text, skill.version + 1)  # 承認の時と同じ書き換えを試すだけ
    except SkillChangeError:
        return "version_line", (
            "frontmatter の version は、字下げなし・引用符なしの「version: 数字」の"
            "1行だけにする"
        )
    return None


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------


def _context(reason: str) -> dict[str, Any]:
    return {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": reason,
        },
    }


def _get(data: Any, key: str) -> Any:
    return data.get(key) if isinstance(data, dict) else None


def _is_target(file_path: Any, target: Path) -> bool:
    if not isinstance(file_path, str) or not file_path:
        return False
    try:
        return Path(file_path).resolve() == target
    except (OSError, RuntimeError, ValueError):
        return False


def _read_problem(target: Path) -> tuple[str | None, Problem | None]:
    try:
        return target.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return None, ("format", "SKILL.md を UTF-8 の文字で書く")
    except (OSError, ValueError):
        return None, ("unreadable", "SKILL.md が読めない（消さずに、同じ場所に置く）")


def _problem(
    file_path: Any, target: Path, skill_name: str, base_version: int | None
) -> Problem | None:
    if not _is_target(file_path, target):
        return "other_file", (
            "アプリが読むのはこのファイルだけ。ほかのファイルへの書き込みは使われない"
        )
    text, problem = _read_problem(target)
    if text is None:
        return problem
    return check_skill_text(skill_name, text, base_version)


def make_skill_check(
    work_root: Path, skill_name: str, base_version: int | None, logger: EventLogger
) -> HookFn:
    """写しの SKILL.md を Write / Edit した直後に検査する PostToolUse の Hook。"""
    if not is_valid_skill_name(skill_name):
        raise ValueError("Skill 名の書式が違う")
    target = _skill_file(Path(work_root).resolve(), skill_name)
    path_text = f"{target}（.claude/skills/{skill_name}/{SKILL_FILE_NAME}）"

    async def skill_check(input_data: Any, tool_use_id: str | None, ctx: Any) -> dict:
        tool_name = _get(input_data, "tool_name")
        if tool_name not in SKILL_CHECK_MATCHER.split("|"):
            return {}
        file_path = _get(_get(input_data, "tool_input"), "file_path")
        try:
            problem = _problem(file_path, target, skill_name, base_version)
        except Exception as exc:  # Hook は例外を出さない（後で service が検査する）
            logger.event(
                "hook_skill_check_error",
                hook_name=HOOK_NAME,
                decision=reason_code("error_type", type(exc).__name__),
            )
            return {}
        fields = {"hook_name": HOOK_NAME, "tool_name": tool_name}
        if problem is None:
            logger.event("hook_skill_check_allow", decision="allow", **fields)
            return {}
        code, reason = problem
        logger.event(
            "hook_skill_check_retry", decision=reason_code("retry", code), **fields
        )
        return _context(_HEAD.format(path=path_text) + reason)

    return skill_check

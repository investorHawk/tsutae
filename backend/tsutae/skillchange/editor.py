"""Skill を書き換えるエージェント（SkillEditor・SdkSkillEditor）。docs/architecture.md §9b。

- `SkillEditor` プロトコル: `async edit(work_root, skill_name, request_text) -> RunStats`。
  work_root は `request_change` が作った一時ディレクトリで、
  `<work_root>/.claude/skills/<skill_name>/SKILL.md`（本体の写し）だけが置かれている
- `build_options` は純関数（query は呼ばない）。Hook は H1（依頼文の二次検出）・
  H4（Read・Edit・Write 以外を deny。サブエージェントは呼ばせない）・
  H3（`make_h3(work_root, logger)`。書き込み先を写しの SKILL.md に限る）と、
  Read を work_root の中に限る read_guard（院内の DB 等を読ませない）、
  PostToolUse の skill_check（check.py。書き込みの直後に検査し、通らなければ
  理由をモデルに返して直させる）
- 依頼文は frontmatter の決まり（Skill の種類ごと）と、regimen Skill なら今の質問の
  key の一覧を含む（新しい key を重ねさせない）。版・key は edit が写しから読む
- Hook が記録するロガーは、プロトコルの引数に無いので `logging_to(logger)` で渡す
  （contextvars。`request_change` が変更依頼ごとの PipelineLogger を設定する）。
  設定されていなければ捨てる（MemoryLogger）
- SDK の失敗（ClaudeSDKError。max_turns・max_budget_usd の ResultError を含む）は、
  直前の ResultMessage の費用・トークン数を `editor_failed`（decision は
  `sdk_error_code` のコード）でログに残し、`RunFailedError`（cause・stats）に包んで
  投げ直す（service が failed と max_turns / max_budget / sdk_error にする）
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    ResultMessage,
    query,
)

from tsutae.config import Settings, get_settings
from tsutae.pipeline.hooks import H3_MATCHER, make_h1, make_h3, make_h4
from tsutae.pipeline.logs import EventLogger, MemoryLogger, reason_code
from tsutae.pipeline.orchestrator import NO_SESSION_PERSISTENCE, sdk_error_code
from tsutae.pipeline.runner import RunFailedError, stats_from_result
from tsutae.schemas import RunStats
from tsutae.skillchange.check import (
    SKILL_CHECK_MATCHER,
    make_skill_check,
    read_baseline,
)
from tsutae.skills import SKILL_FILE_NAME, is_valid_skill_name

__all__ = [
    "EDITOR_ALLOWED_TOOLS",
    "EDITOR_DISALLOWED_TOOLS",
    "EDITOR_MAX_TURNS",
    "EDITOR_SYSTEM_PROMPT",
    "SdkSkillEditor",
    "SkillEditor",
    "build_options",
    "build_prompt",
    "current_logger",
    "logging_to",
    "relative_skill_path",
]

QueryFn = Callable[..., AsyncIterator[Any]]
HookFn = Callable[[Any, str | None, Any], Any]

EDITOR_ALLOWED_TOOLS: tuple[str, ...] = ("Read", "Edit", "Write")
EDITOR_DISALLOWED_TOOLS: tuple[str, ...] = (
    "Bash",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
    "Skill",
    "MultiEdit",
    "NotebookEdit",
    "Workflow",
    "Glob",
    "Grep",
)
# 読む1・書く1〜2（frontmatter と本文）・skill_check の理由で直す数回（読み直しを
# 含めて1回2ターン）・締め1。費用は max_budget_usd でも止まる
EDITOR_MAX_TURNS = 16
READ_MATCHER = "Read"

EDITOR_SYSTEM_PROMPT = (
    "あなたは外来化学療法の記録アプリ「つたえ」の Skill（SKILL.md）を書き換える係。"
    "医師の依頼の一文に従い、作業ディレクトリにある1つの SKILL.md だけを、"
    "Read で読んでから Edit で最小限に直す。ほかのファイルは読まない・作らない。"
    "frontmatter（最初の --- と --- の間の YAML）はアプリが機械で読むので、"
    "YAML として正しい形とキーの名前を保ち、キーを重複させない。"
    "name と version は変えない（版はアプリが承認の時に上げる）。"
    "Grade・重さの判定・助言・原因の推測を足さない。"
    "質問文は患者が画面で読む、このアプリ独自のやさしい文言にする"
    "（PRO-CTCAE など既存の質問票の文言を写さない）。質問に助言・説明・重さの"
    "判定の基準を入れない。"
    "frontmatter を変えたら、本文の説明（質問の一覧・対応表など）も食い違わない"
    "よう必要なだけ合わせて直す。"
    "書き込むたびにアプリが検査し、通らなければ理由を返すので、理由のとおりに直す。"
    "依頼が Skill の書き換えとして意味をなさないときは、何も書き換えずに終える。"
)
_REGIMEN_RULES = (
    "- questions の各項目は key・text・answer_type の3つ。key は英小文字で始まり"
    "英小文字・数字・下線の2〜41字で、重複させない。text は1〜200字。answer_type は"
    " three_level（なし・ある・つらい）か temperature（体温）のどちらか\n"
    "- 今の key は変えない・別の意味に使い回さない（過去の記録がその key を指す）\n"
    "- fixed_rules の question_key は questions にある temperature の質問の key。"
    "threshold_celsius は 35.0〜42.0。patient_string_key は変えない\n"
    "- cycle_days は 7〜42。pump_removal_day は 1 以上 cycle_days 以下"
    "（無い Skill には足さない）。regimen は変えない\n"
)
_REPORT_RULES = (
    "- sections は header・attention・grid・per_symptom・quotes から1つ以上\n"
    "- quotes_max_items は 0〜200、low_confidence_threshold は 0〜1、"
    "fever_attention_celsius は 35.0〜42.0\n"
)

_LOGGER: ContextVar[EventLogger | None] = ContextVar(
    "tsutae_skillchange_logger", default=None
)


# ---------------------------------------------------------------------------
# ロガーの受け渡し
# ---------------------------------------------------------------------------


@contextmanager
def logging_to(logger: EventLogger) -> Iterator[EventLogger]:
    """この中で動く SdkSkillEditor の Hook の記録先を logger にする。"""
    token = _LOGGER.set(logger)
    try:
        yield logger
    finally:
        _LOGGER.reset(token)


def current_logger() -> EventLogger:
    logger = _LOGGER.get()
    return logger if logger is not None else MemoryLogger()


# ---------------------------------------------------------------------------
# 依頼文
# ---------------------------------------------------------------------------


def relative_skill_path(skill_name: str) -> str:
    if not is_valid_skill_name(skill_name):
        raise ValueError("Skill 名の書式が違う")
    return f".claude/skills/{skill_name}/{SKILL_FILE_NAME}"


def _rules(skill_name: str, question_keys: Sequence[str]) -> str:
    if not skill_name.startswith("regimen-"):
        return _REPORT_RULES
    keys = ""
    if question_keys:
        keys = (
            f"- 今の質問の key: {', '.join(question_keys)}。質問を足すときは、"
            "これと重ならない新しい key にする\n"
        )
    return _REGIMEN_RULES + keys


def build_prompt(
    skill_name: str, request_text: str, *, question_keys: Sequence[str] = ()
) -> str:
    """主エージェントへの依頼文。H1 に掛からないよう、敬称・版の文字列を書かない。

    question_keys は regimen Skill の今の質問の key（写しから読んだもの）。
    """
    path = relative_skill_path(skill_name)
    return (
        f"作業ディレクトリの {path} を、下の依頼に従って書き換える。\n"
        "- 書き換えてよいのはこのファイルだけ。file_path は作業ディレクトリからの"
        "絶対パスにする\n"
        "- frontmatter の name と version の行は変えない\n"
        "- 依頼に関係のない行は変えない\n"
        "\n"
        "frontmatter の決まり:\n"
        f"{_rules(skill_name, question_keys)}"
        "\n"
        "依頼（医師の一文。<<< と >>> の間）:\n"
        f"<<<\n{request_text}\n>>>\n"
    )


# ---------------------------------------------------------------------------
# Hook と options
# ---------------------------------------------------------------------------


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _read_problem(file_path: Any, root: Path) -> str | None:
    if not isinstance(file_path, str) or not file_path:
        return "no_file_path"
    path = Path(file_path)
    if not path.is_absolute():
        return "not_absolute"
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return "unresolvable"
    return None if resolved.is_relative_to(root) else "outside_work_root"


def make_read_guard(work_root: Path, logger: EventLogger) -> HookFn:
    """Read を work_root の中（resolve 後）に限る。"""
    root = Path(work_root).resolve()

    async def read_guard(input_data: Any, tool_use_id: str | None, ctx: Any) -> dict:
        data = input_data if isinstance(input_data, dict) else {}
        if data.get("tool_name") != READ_MATCHER:
            return {}
        tool_input = data.get("tool_input")
        file_path = (
            tool_input.get("file_path") if isinstance(tool_input, dict) else None
        )
        code = _read_problem(file_path, root)
        if code is None:
            logger.event("hook_read_allow", hook_name="read_guard", decision="allow")
            return {}
        logger.event(
            "hook_read_deny", hook_name="read_guard", decision=reason_code("deny", code)
        )
        return _deny("読めるのは作業ディレクトリの中だけ（file_path は絶対パス）")

    return read_guard


def _matcher(hook: HookFn, matcher: str | None = None) -> HookMatcher:
    return HookMatcher(matcher=matcher, hooks=[hook], on_failure="block")


def build_hooks(
    work_root: Path,
    logger: EventLogger,
    *,
    skill_name: str,
    base_version: int | None = None,
) -> dict[str, list[HookMatcher]]:
    check = make_skill_check(work_root, skill_name, base_version, logger)
    return {
        "UserPromptSubmit": [_matcher(make_h1(logger))],
        "PreToolUse": [
            _matcher(make_h4(EDITOR_ALLOWED_TOOLS, (), logger)),
            _matcher(make_h3(work_root, logger), H3_MATCHER),
            _matcher(make_read_guard(work_root, logger), READ_MATCHER),
        ],
        # H3 が通した書き込みの直後に、写しの SKILL.md を検査する
        "PostToolUse": [_matcher(check, SKILL_CHECK_MATCHER)],
    }


def build_options(
    work_root: Path,
    settings: Settings,
    logger: EventLogger,
    *,
    skill_name: str,
    base_version: int | None = None,
) -> ClaudeAgentOptions:
    """書き換え1回分の ClaudeAgentOptions（純関数。query は呼ばない）。

    base_version は写しの元の版（skill_check が「version が元のまま」を見る）。
    """
    hooks = build_hooks(
        work_root, logger, skill_name=skill_name, base_version=base_version
    )
    return ClaudeAgentOptions(
        cwd=str(work_root),
        setting_sources=["project"],
        model=settings.model,
        allowed_tools=list(EDITOR_ALLOWED_TOOLS),
        disallowed_tools=list(EDITOR_DISALLOWED_TOOLS),
        # 会話の記録（依頼文・Skill の本文）を ~/.claude/projects/ に残さない
        extra_args=dict(NO_SESSION_PERSISTENCE),
        permission_mode="acceptEdits",
        hooks=hooks,  # type: ignore[arg-type]
        max_turns=EDITOR_MAX_TURNS,
        max_budget_usd=settings.pipeline_max_budget_usd,
        system_prompt=EDITOR_SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# エディタ
# ---------------------------------------------------------------------------


@runtime_checkable
class SkillEditor(Protocol):
    async def edit(
        self, work_root: Path, skill_name: str, request_text: str
    ) -> RunStats: ...


class SdkSkillEditor:
    """`claude_agent_sdk.query` で写しの SKILL.md を書き換える。"""

    def __init__(
        self, settings: Settings | None = None, query_fn: QueryFn | None = None
    ) -> None:
        self.settings = settings
        self.query_fn: QueryFn = query_fn if query_fn is not None else query

    async def edit(
        self, work_root: Path, skill_name: str, request_text: str
    ) -> RunStats:
        settings = self.settings if self.settings is not None else get_settings()
        logger = current_logger()
        baseline = read_baseline(Path(work_root), skill_name)
        options = build_options(
            Path(work_root),
            settings,
            logger,
            skill_name=skill_name,
            base_version=baseline.version,
        )
        prompt = build_prompt(
            skill_name, request_text, question_keys=baseline.question_keys
        )
        result: ResultMessage | None = None
        try:
            async for message in self.query_fn(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result = message
        except ClaudeSDKError as exc:
            raise _failed(exc, result, logger) from exc
        return stats_from_result(result)


def _failed(
    exc: ClaudeSDKError, result: ResultMessage | None, logger: EventLogger
) -> RunFailedError:
    """失敗の直前の ResultMessage の費用・トークン数をログに残し、添えて返す。

    CLI は失敗（max_turns・max_budget_usd など）でも is_error の ResultMessage を
    返してから ResultError を出す。例外の本文はログに入れない（コードだけ）。
    """
    stats = stats_from_result(result)
    logger.event(
        "editor_failed",
        decision=sdk_error_code(exc),
        **stats.model_dump(exclude={"num_turns"}),
    )
    return RunFailedError(exc, stats)

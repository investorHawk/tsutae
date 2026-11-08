"""変換1回分の組み立てと実行（build_options・convert）。docs/architecture.md §7。

convert の手順:
1. 自由記載の記録が1件も無い（masked_texts が空。記録0件を含む）なら Claude を呼ばず、
   unprocessed だけの Timeline で成功（§7 W2b。H2 が引用を全て拒否するので、呼んでも
   出せる結果は空だけ）
2. settings.skills_dir が `<home>/.claude/skills` の形でなければ config_error（SDK は cwd の
   `.claude/skills` しか読まない。黙って既定に替えると、prepare_input・report が読んだ
   Skill と SDK が読む Skill が別物になる）
3. コードで `detect_identifiers(依頼文)` → 掛かれば h1_blocked（UserPromptSubmit の H1 と二重）。
   医師が確かめて許した語（prepared.allowed_suspects）に完全に含まれる検出だけは
   H1 と同じく無視する（`masking.manual.detect_in_prompt`。空なら今と同じ）
4. 実行直前に、ディスク上（`<home>/.claude/skills`）の両 Skill の版が入力の版
   （regimen_skill_version・report_skill_version）と一致するかを確かめる。違えば
   skill_version_mismatch、読めなければ skill_load_error（どちらも Claude を呼ばない）。
   SDK は名前で現在の Skill を読むので、入力準備後に Skill が更新されると、質問・日程・版は
   旧版のままモデルだけが新版の本文に従う競合になる。ログは `skill_check`（ok /
   mismatch:<名前> / load_error:<名前>）。照合から SDK の読み込みまでの短い間の更新は防げない
5. `asyncio.wait_for(runner.run(...), settings.pipeline_timeout_s)`
6. TimeoutError → timeout、ClaudeSDKError（ResultError を含む）→ max_budget_usd 超過なら
   max_budget、max turns なら max_turns、他は sdk_error（`sdk_error_code`）、
   それ以外の例外 → internal_error、emit_timeline が来ない → no_timeline、
   emit_report が来ない → no_report（統合役は timeline と report の両方を出す。spec §7.1）
7. 成功なら timeline に unprocessed を足して返す

失敗でも、runner が `RunFailedError.stats`（失敗の ResultMessage の費用・トークン数）を
添えていればそれを stats に使う（所要時間が無ければ経過時間）。

例外は外へ出さない（取り消し CancelledError だけはそのまま通す）。例外の本文はログに
入れない（コードだけ）。internal_error のときは例外の**型名だけ**を `internal_error` の
decision に `error_type:<型名>` で残し、Python の logging にも型名だけを出す。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultError

from tsutae.config import Settings
from tsutae.masking.manual import detect_in_prompt
from tsutae.pipeline.agents import AGENT_NAMES, build_agents
from tsutae.pipeline.hooks import build_hooks
from tsutae.pipeline.logs import EventLogger, reason_code
from tsutae.pipeline.prompt import SYSTEM_PROMPT, build_prompt
from tsutae.pipeline.runner import AgentRunner, RunFailedError
from tsutae.pipeline.tools import (
    EMIT_REPORT_TOOL,
    EMIT_TIMELINE_TOOL,
    SERVER_NAME,
    RunCollector,
    build_server,
)
from tsutae.schemas import (
    ConversionResult,
    PreparedInput,
    ReportPicks,
    RunStats,
    Timeline,
)
from tsutae.skills import is_valid_skill_name, load_skill

__all__ = [
    "ALLOWED_TOOLS",
    "DISALLOWED_TOOLS",
    "NO_SESSION_PERSISTENCE",
    "build_options",
    "convert",
    "sdk_error_code",
]

# サブエージェント起動ツールは init では Task、Hook では Agent（T03）
ALLOWED_TOOLS: tuple[str, ...] = (
    "Task",
    "Agent",
    "Skill",
    EMIT_TIMELINE_TOOL,
    EMIT_REPORT_TOOL,
)
DISALLOWED_TOOLS: tuple[str, ...] = (
    "Bash",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Workflow",
    "Read",
    "Glob",
    "Grep",
    # 遅延読み込み（ToolSearch 経由でしか MCP ツールに届かない）を切る。同梱 CLI は
    # ToolSearch が disallowedTools にあると tool search を無効にする（CLI の文字列
    # 「Tool search disabled: ToolSearchTool is not available (may have been disallowed
    # via disallowedTools)」で確認。2026-11-04）。H4 も ToolSearch を許していない
    "ToolSearch",
    # 使わない組み込みツール（T03 の init に出たもの）。H4 も拒否するが、説明文が
    # コンテキストに載り、誤って呼ぶと max_turns を使う
    "CronCreate",
    "CronDelete",
    "CronList",
    "DesignSync",
    "EnterWorktree",
    "ExitWorktree",
    "ListAgents",
    "Monitor",
    "PushNotification",
    "ReportFindings",
    "ScheduleWakeup",
    "SendMessage",
    "TaskStop",
)
# 会話の記録（依頼文＝伏せ字後の自由記載、サブエージェントの出力、emit_* の引数＝
# 変換結果）を ~/.claude/projects/<cwd>/<session>.jsonl に書かせない（spec §13.3）。
# SDK の transport は既定でこのフラグを付けない。このフラグは .jsonl を止めるだけで、
# CLI は <session>/subagents/agent-*.meta.json（モデルが書いた description を含む）を
# 書くので、実行の後に runner（session_files.query_cleaned）がセッションのディレクトリを消す
NO_SESSION_PERSISTENCE: dict[str, str | None] = {"no-session-persistence": None}
# setting_sources=["project"] は cwd と全ての祖先の CLAUDE.md も読む（system_prompt を
# 文字列にしても止まらない）。リポジトリ直下の開発用 CLAUDE.md を変換の文脈に入れない
NO_CLAUDE_MD_ENV: dict[str, str] = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}
_log = logging.getLogger(__name__)
_MAX_TURNS_RE = re.compile(
    r"max(?:imum)?[\s_-]*(?:number[\s_-]+of[\s_-]+)?turns", re.IGNORECASE
)
_MAX_BUDGET_RE = re.compile(r"budget", re.IGNORECASE)


def _skill_name(skill_version: str) -> str:
    name = skill_version.split("@", 1)[0]
    if not is_valid_skill_name(name):
        raise ValueError("skill_version の Skill 名が不正")
    return name


def _skills_home(settings: Settings) -> Path | None:
    """settings.skills_dir（<home>/.claude/skills）から cwd にする <home>。形が違えば None。"""
    skills_dir = Path(settings.skills_dir)
    if skills_dir.name == "skills" and skills_dir.parent.name == ".claude":
        return skills_dir.parent.parent
    return None


def build_options(
    prepared: PreparedInput,
    collector: RunCollector,
    logger: EventLogger,
    settings: Settings,
    skills_home: Path,
) -> ClaudeAgentOptions:
    regimen_skill = _skill_name(prepared.input.regimen_skill_version)
    report_skill = _skill_name(prepared.input.report_skill_version)
    return ClaudeAgentOptions(
        cwd=str(skills_home),
        setting_sources=["project"],
        skills=[regimen_skill, report_skill],
        model=settings.model,
        agents=build_agents(settings, regimen_skill, term_keys=prepared.term_keys),
        mcp_servers={SERVER_NAME: build_server(collector)},
        allowed_tools=list(ALLOWED_TOOLS),
        disallowed_tools=list(DISALLOWED_TOOLS),
        permission_mode="dontAsk",
        hooks=build_hooks(  # type: ignore[arg-type]
            masked_texts=prepared.masked_texts,
            logger=logger,
            allowed_tools=ALLOWED_TOOLS,
            allowed_subagents=AGENT_NAMES,
            expected_prompt=build_prompt(prepared),
            allowed_suspects=tuple(prepared.allowed_suspects),
        ),
        max_turns=settings.pipeline_max_turns,
        max_budget_usd=settings.pipeline_max_budget_usd,
        system_prompt=SYSTEM_PROMPT,
        extra_args=dict(NO_SESSION_PERSISTENCE),
        env=dict(NO_CLAUDE_MD_ENV),
    )


def _check_skill_versions(
    prepared: PreparedInput, skills_home: Path, logger: EventLogger
) -> str | None:
    """ディスク上の Skill の版が入力の版と違えば error_code（一致すれば None）。"""
    skills_dir = skills_home / ".claude" / "skills"
    for expected in (
        prepared.input.regimen_skill_version,
        prepared.input.report_skill_version,
    ):
        name = _skill_name(expected)
        try:
            current = load_skill(name, skills_dir).skill_version
        except (OSError, ValueError):  # SkillValidationError は ValueError
            logger.event("skill_check", decision=reason_code("load_error", name))
            return "skill_load_error"
        if current != expected:
            logger.event("skill_check", decision=reason_code("mismatch", name))
            return "skill_version_mismatch"
    logger.event("skill_check", decision="ok")
    return None


def _elapsed(started: float) -> RunStats:
    return RunStats(duration_ms=int((time.monotonic() - started) * 1000))


def _failed_stats(exc: ClaudeSDKError, started: float) -> RunStats:
    """失敗の ResultMessage の費用・トークン数（無ければ経過時間だけ）。"""
    stats = exc.stats if isinstance(exc, RunFailedError) else RunStats()
    if stats.duration_ms > 0:
        return stats
    return stats.model_copy(update={"duration_ms": _elapsed(started).duration_ms})


def _fallback(code: str, stats: RunStats) -> ConversionResult:
    return ConversionResult(
        timeline=None, picks=None, fallback=True, error_code=code, stats=stats
    )


def _result_error_code(exc: ResultError) -> str | None:
    """CLI の result の subtype・terminal_reason から（分からなければ None）。"""
    subtype = exc.subtype or ""
    reason = exc.terminal_reason or ""
    if "max_budget" in subtype or "budget" in reason:
        return "max_budget"
    if "max_turns" in subtype or reason == "max_turns":
        return "max_turns"
    return None


def sdk_error_code(exc: BaseException) -> str:
    """ClaudeSDKError（RunFailedError は中身）の短いコード。

    max_budget_usd 超過（subtype `error_max_budget_usd`、または本文に budget）は
    max_budget、max_turns 超過は max_turns、他は sdk_error。D4（skillchange）も使う。
    """
    if isinstance(exc, RunFailedError):
        exc = exc.cause
    if isinstance(exc, ResultError):
        code = _result_error_code(exc)
        if code is not None:
            return code
    text = str(exc)
    if _MAX_BUDGET_RE.search(text):
        return "max_budget"
    return "max_turns" if _MAX_TURNS_RE.search(text) else "sdk_error"


def _empty_result(prepared: PreparedInput) -> ConversionResult:
    timeline = Timeline(unprocessed_entries=list(prepared.unprocessed))
    return ConversionResult(timeline=timeline, picks=ReportPicks(), fallback=False)


async def _run(
    prepared: PreparedInput,
    runner: AgentRunner,
    logger: EventLogger,
    settings: Settings,
    skills_home: Path,
) -> ConversionResult:
    started = time.monotonic()
    prompt = build_prompt(prepared)
    found = detect_in_prompt(prompt, tuple(prepared.allowed_suspects))
    if found:
        logger.event(
            "hook_h1_block",
            hook_name="H1",
            decision=reason_code("block", found[0].rule),
        )
        return _fallback("h1_blocked", RunStats())
    skill_error = _check_skill_versions(prepared, skills_home, logger)
    if skill_error is not None:
        return _fallback(skill_error, RunStats())
    collector = RunCollector.from_prepared(prepared, logger=logger)
    options = build_options(prepared, collector, logger, settings, skills_home)
    try:
        stats = await asyncio.wait_for(
            runner.run(prompt, options, collector), timeout=settings.pipeline_timeout_s
        )
    except TimeoutError:
        return _fallback("timeout", _elapsed(started))
    except ClaudeSDKError as exc:
        return _fallback(sdk_error_code(exc), _failed_stats(exc, started))
    if collector.timeline is None:
        return _fallback("no_timeline", stats)
    if collector.picks is None:
        return _fallback("no_report", stats)
    timeline = Timeline(
        events=list(collector.timeline.events),
        contradictions=list(collector.timeline.contradictions),
        unprocessed_entries=list(prepared.unprocessed),
    )
    return ConversionResult(
        timeline=timeline, picks=collector.picks, fallback=False, stats=stats
    )


def _finish(logger: EventLogger, result: ConversionResult) -> ConversionResult:
    if result.fallback:
        logger.event("fallback", decision=result.error_code)
    stats = result.stats
    logger.event(
        "run_end",
        decision=result.error_code or "ok",
        duration_ms=stats.duration_ms,
        tokens_in=stats.tokens_in,
        tokens_out=stats.tokens_out,
        cost_usd=stats.cost_usd,
    )
    return result


async def convert(
    prepared: PreparedInput,
    *,
    runner: AgentRunner,
    logger: EventLogger,
    settings: Settings,
    skills_home: Path | None = None,
) -> ConversionResult:
    """1回の変換。失敗は全てフォールバック（timeline=None）で返し、例外を出さない。"""
    logger.event("run_start")
    if not prepared.masked_texts:
        return _finish(logger, _empty_result(prepared))
    home = skills_home if skills_home is not None else _skills_home(settings)
    if home is None:
        logger.event("config_error", decision="skills_dir_shape")
        return _finish(logger, _fallback("config_error", RunStats()))
    try:
        result = await _run(prepared, runner, logger, settings, home)
    except asyncio.CancelledError:
        raise
    except (
        Exception
    ) as exc:  # noqa: BLE001 — 契約: 例外を外へ出さない（本文は残さない）
        result = _internal_error(logger, exc)
    return _finish(logger, result)


def _internal_error(logger: EventLogger, exc: Exception) -> ConversionResult:
    """想定外の例外。型名だけを残す（本文は患者の文を含みうるので残さない）。"""
    error_type = type(exc).__name__
    logger.event("internal_error", decision=reason_code("error_type", error_type))
    _log.warning("pipeline internal_error: %s", error_type)
    return _fallback("internal_error", RunStats())

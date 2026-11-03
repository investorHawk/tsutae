"""変換パイプラインの Hook（docs/architecture.md §7、spec §8）。

- H1 UserPromptSubmit: 依頼文に二次検出（detect_identifiers）が掛かれば全体を止める
- H2 PreToolUse（emit_timeline / emit_report）: 引用が伏せ字後の原文の部分文字列で
  なければ deny（理由は項目の番号だけ。原文は入れない）
- H3 PreToolUse（Write / Edit / MultiEdit）: D4 の Skill 書き換え先を
  `<skills_root>/.claude/skills/<SKILL_NAME_PATTERN>/SKILL.md` に限る（resolve 後に判定）
- H4 PreToolUse（全ツール）: 許可外のツールと、3役以外のサブエージェントを deny
- trace: SubagentStart / SubagentStop / PostToolUse を記録するだけ（D5）

コールバックは async で (input, tool_use_id, context) を受け、意見が無ければ {} を返す。
例外を出すと on_failure="block" で止まるので、壊れた入力も deny で返す。

ログ（spec §8「Hook の発火を D5 とテストで確認できる」）: 止めた時は `hook_hN_block` /
`hook_hN_deny`、通した時も `hook_hN_allow`（decision="allow"）を残す。PostToolUse は
ツールが動いたことしか示さないため。受け持ちでないツール（H2・H3 の matcher 外）は
記録しない。文面は入れない（規則名・項目の位置などのコードだけ）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher

from tsutae.masking import detect_identifiers
from tsutae.pipeline.logs import EventLogger, reason_code
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL
from tsutae.skills import SKILL_FILE_NAME, is_valid_skill_name

__all__ = [
    "H2_MATCHER",
    "H3_MATCHER",
    "SUBAGENT_TOOLS",
    "build_hooks",
    "make_h1",
    "make_h2",
    "make_h3",
    "make_h4",
    "make_trace_hooks",
]

HookFn = Callable[[Any, str | None, Any], Awaitable[dict[str, Any]]]
Problem = tuple[str, str]  # (項目の位置, 理由)

H2_MATCHER = f"{EMIT_TIMELINE_TOOL}|{EMIT_REPORT_TOOL}"
H3_MATCHER = "Write|Edit|MultiEdit"
SUBAGENT_TOOLS = ("Agent", "Task")  # init では Task、Hook では Agent（T03）
MAX_PROBLEMS = 20
ALLOW = "allow"
H2_REASON_HEAD = (
    "引用の検査で拒否した（このツールの入力は何も受け付けていない）。引用はその"
    " entry_no の masked_free_text の部分文字列を一字も変えずに使う（句読点・空白・改行"
    "・全角半角・伏せ字も原文のまま。要約・言い換え・つなぎ合わせをしない）。挙げた項目を"
    "直し、全体をもう一度渡す（引用のほかの項目はこの後に検査する）: "
)


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


# ---------------------------------------------------------------------------
# H1
# ---------------------------------------------------------------------------


def make_h1(logger: EventLogger) -> HookFn:
    async def h1(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
        prompt = _get(input_data, "prompt")
        if isinstance(prompt, str):
            found = detect_identifiers(prompt)
            if not found:
                logger.event("hook_h1_allow", hook_name="H1", decision=ALLOW)
                return {}
            rule = found[0].rule
        else:
            rule = "invalid_prompt"
        logger.event(
            "hook_h1_block", hook_name="H1", decision=reason_code("block", rule)
        )
        return {
            "decision": "block",
            "reason": rule,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "suppressOriginalPrompt": True,
            },
        }

    return h1


# ---------------------------------------------------------------------------
# H2
# ---------------------------------------------------------------------------


def _entry_no(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _usable_quote(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _quote_problem(
    item: Any, where: str, key: str, texts: Mapping[int, str]
) -> Problem | None:
    if not isinstance(item, dict):
        return where, "オブジェクトでない"
    no = _entry_no(item.get("entry_no"))
    if no is None or no not in texts:
        return (
            f"{where}.entry_no",
            "自由記載のある記録の entry_no でない（masked_free_text が null の記録"
            "・入力に無い番号からは作らない）",
        )
    quote = _usable_quote(item.get(key))
    if quote is None:
        return f"{where}.{key}", "引用が無い"
    if quote not in texts[no]:
        return f"{where}.{key}", f"entry_no={no} の masked_free_text の部分文字列でない"
    return None


def _timeline_problems(tool_input: dict, texts: Mapping[int, str]) -> list[Problem]:
    problems: list[Problem] = []
    for key, quote_key, default in (
        ("events", "source_quote", None),
        ("contradictions", "free_text_quote", []),
    ):
        items = tool_input.get(key, default)
        if not isinstance(items, list):
            problems.append((key, "配列でない"))
            continue
        for i, item in enumerate(items):
            problem = _quote_problem(item, f"{key}.{i}", quote_key, texts)
            if problem is not None:
                problems.append(problem)
    return problems


def _report_problems(tool_input: dict, texts: Mapping[int, str]) -> list[Problem]:
    items = tool_input.get("per_symptom")
    if not isinstance(items, list):
        return [("per_symptom", "配列でない")]
    problems: list[Problem] = []
    for i, item in enumerate(items):
        where = f"per_symptom.{i}.representative_quote"
        quote = _usable_quote(_get(item, "representative_quote"))
        if quote is None:
            problems.append((where, "引用が無い"))
        elif not any(quote in text for text in texts.values()):
            problems.append(
                (
                    where,
                    "どの masked_free_text の部分文字列でもない（受け付けた events の"
                    " source_quote を丸ごとそのまま使う）",
                )
            )
    return problems


def _h2_reason(problems: list[Problem]) -> str:
    shown = [f"{where}（{why}）" for where, why in problems[:MAX_PROBLEMS]]
    if len(problems) > MAX_PROBLEMS:
        shown.append(f"ほか {len(problems) - MAX_PROBLEMS} 件")
    return H2_REASON_HEAD + "; ".join(shown)


def make_h2(masked_texts: Mapping[int, str], logger: EventLogger) -> HookFn:
    texts = dict(masked_texts)

    async def h2(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
        tool_name = _get(input_data, "tool_name")
        if tool_name not in (EMIT_TIMELINE_TOOL, EMIT_REPORT_TOOL):
            return {}
        tool_input = _get(input_data, "tool_input")
        if not isinstance(tool_input, dict):
            problems: list[Problem] = [("(root)", "オブジェクトでない")]
        elif tool_name == EMIT_TIMELINE_TOOL:
            problems = _timeline_problems(tool_input, texts)
        else:
            problems = _report_problems(tool_input, texts)
        fields = {"tool_name": tool_name, "agent_type": _get(input_data, "agent_type")}
        if not problems:
            logger.event("hook_h2_allow", hook_name="H2", decision=ALLOW, **fields)
            return {}
        logger.event(
            "hook_h2_deny",
            hook_name="H2",
            decision=reason_code("deny", problems[0][0]),
            **fields,
        )
        return _deny(_h2_reason(problems))

    return h2


# ---------------------------------------------------------------------------
# H3
# ---------------------------------------------------------------------------


def _skill_file_problem(file_path: Any, skills_dir: Path) -> str | None:
    if not isinstance(file_path, str) or not file_path:
        return "no_file_path"
    path = Path(file_path)
    if not path.is_absolute():
        return "not_absolute"
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return "unresolvable"
    if (
        resolved.name != SKILL_FILE_NAME
        or resolved.parent.parent != skills_dir
        or not is_valid_skill_name(resolved.parent.name)
    ):
        return "outside_skills"
    return None


def make_h3(skills_root: Path, logger: EventLogger) -> HookFn:
    root = Path(skills_root)

    async def h3(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
        tool_name = _get(input_data, "tool_name")
        if tool_name not in H3_MATCHER.split("|"):
            return {}
        skills_dir = (root / ".claude" / "skills").resolve()
        code = _skill_file_problem(
            _get(_get(input_data, "tool_input"), "file_path"), skills_dir
        )
        fields = {"tool_name": tool_name, "agent_type": _get(input_data, "agent_type")}
        if code is None:
            logger.event("hook_h3_allow", hook_name="H3", decision=ALLOW, **fields)
            return {}
        logger.event(
            "hook_h3_deny", hook_name="H3", decision=reason_code("deny", code), **fields
        )
        return _deny(
            "書き込めるのは .claude/skills/<Skill 名>/SKILL.md だけ（Skill 名は regimen- か"
            " report-format- で始まる。file_path は絶対パス）"
        )

    return h3


# ---------------------------------------------------------------------------
# H4
# ---------------------------------------------------------------------------


def _h4_problem(
    input_data: Any, tools: frozenset[str], agents: frozenset[str]
) -> str | None:
    tool_name = _get(input_data, "tool_name")
    if not isinstance(tool_name, str) or tool_name not in tools:
        return "tool_not_allowed"
    if tool_name in SUBAGENT_TOOLS:
        subagent = _get(_get(input_data, "tool_input"), "subagent_type")
        if not isinstance(subagent, str) or subagent not in agents:
            return "subagent_not_allowed"
    return None


def make_h4(
    allowed_tools: Iterable[str], allowed_subagents: Iterable[str], logger: EventLogger
) -> HookFn:
    tools = frozenset(allowed_tools)
    agents = frozenset(allowed_subagents)
    messages = {
        "tool_not_allowed": "このツールは使えない。使えるのは "
        + ", ".join(sorted(tools)),
        "subagent_not_allowed": "呼べるサブエージェントは " + ", ".join(sorted(agents)),
    }

    async def h4(input_data: Any, tool_use_id: str | None, context: Any) -> dict:
        code = _h4_problem(input_data, tools, agents)
        fields = {
            "tool_name": _get(input_data, "tool_name"),
            "agent_type": _get(input_data, "agent_type"),
        }
        if code is None:
            logger.event("hook_h4_allow", hook_name="H4", decision=ALLOW, **fields)
            return {}
        logger.event(
            "hook_h4_deny", hook_name="H4", decision=reason_code("deny", code), **fields
        )
        return _deny(messages[code])

    return h4


# ---------------------------------------------------------------------------
# trace / まとめ
# ---------------------------------------------------------------------------


def make_trace_hooks(logger: EventLogger) -> dict[str, HookFn]:
    """SubagentStart / SubagentStop / PostToolUse を記録するだけ（文面は残さない）。"""

    async def on_subagent_start(input_data: Any, tool_use_id: str | None, ctx: Any):
        logger.event("subagent_start", agent_type=_get(input_data, "agent_type"))
        return {}

    async def on_subagent_stop(input_data: Any, tool_use_id: str | None, ctx: Any):
        logger.event("subagent_stop", agent_type=_get(input_data, "agent_type"))
        return {}

    async def on_post_tool_use(input_data: Any, tool_use_id: str | None, ctx: Any):
        logger.event(
            "tool_use",
            tool_name=_get(input_data, "tool_name"),
            agent_type=_get(input_data, "agent_type"),
            duration_ms=_get(input_data, "duration_ms"),
        )
        return {}

    return {
        "SubagentStart": on_subagent_start,
        "SubagentStop": on_subagent_stop,
        "PostToolUse": on_post_tool_use,
    }


def _matcher(hook: HookFn, matcher: str | None = None) -> HookMatcher:
    return HookMatcher(matcher=matcher, hooks=[hook], on_failure="block")


def build_hooks(
    *,
    masked_texts: Mapping[int, str],
    logger: EventLogger,
    allowed_tools: Iterable[str],
    allowed_subagents: Iterable[str],
) -> dict[str, list[HookMatcher]]:
    """変換1回分の Hook（H1・H4・H2・trace）。H3 は D4 の書き換えで使う。"""
    trace = make_trace_hooks(logger)
    return {
        "UserPromptSubmit": [_matcher(make_h1(logger))],
        "PreToolUse": [
            _matcher(make_h4(allowed_tools, allowed_subagents, logger)),
            _matcher(make_h2(masked_texts, logger), H2_MATCHER),
        ],
        "PostToolUse": [_matcher(trace["PostToolUse"])],
        "SubagentStart": [_matcher(trace["SubagentStart"])],
        "SubagentStop": [_matcher(trace["SubagentStop"])],
    }

"""tsutae.pipeline.runner（AgentRunner・SdkRunner）。query は偽物に差し替える。"""

from __future__ import annotations

from typing import Any

import claude_agent_sdk
import pytest
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultError,
    ResultMessage,
    SystemMessage,
)
from pipeline_fakes import FakeRunner, RaisingRunner, SlowRunner, prepare_case

from tsutae.pipeline.runner import (
    AgentRunner,
    RunFailedError,
    SdkRunner,
    stats_from_result,
)
from tsutae.pipeline.tools import RunCollector
from tsutae.schemas import RunStats

COLLECTOR_INPUT = prepare_case("demo_patient")


def _collector() -> RunCollector:
    return RunCollector.from_prepared(COLLECTOR_INPUT)


def _result(**over: Any) -> ResultMessage:
    base: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 1234,
        "duration_api_ms": 1000,
        "is_error": False,
        "num_turns": 7,
        "session_id": "s",
        "total_cost_usd": 0.42,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 5,
        },
    }
    return ResultMessage(**{**base, **over})


def test_stats_from_result_reads_usage_and_cost() -> None:
    assert stats_from_result(_result()) == RunStats(
        duration_ms=1234, num_turns=7, tokens_in=125, tokens_out=50, cost_usd=0.42
    )


def test_stats_prefers_model_usage_which_includes_subagents() -> None:
    model_usage = {
        "claude-opus-5-5": {
            "inputTokens": 100,
            "outputTokens": 40,
            "cacheReadInputTokens": 10,
            "cacheCreationInputTokens": 0,
            "costUSD": 0.3,
        },
        "claude-sonnet-5-5": {
            "inputTokens": 300,
            "outputTokens": 60,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 2,
            "costUSD": 0.1,
        },
    }
    stats = stats_from_result(_result(model_usage=model_usage))
    assert stats.tokens_in == 412 and stats.tokens_out == 100


def test_stats_tolerate_missing_or_bad_values() -> None:
    assert stats_from_result(None) == RunStats()
    stats = stats_from_result(
        _result(usage={"input_tokens": None, "output_tokens": -3}, total_cost_usd=None)
    )
    assert stats == RunStats(duration_ms=1234, num_turns=7)


def _fake_query(messages: list[Any], seen: list[dict[str, Any]]):
    async def fake_query(*, prompt: str, options: ClaudeAgentOptions):
        seen.append({"prompt": prompt, "options": options})
        for message in messages:
            yield message

    return fake_query


async def test_sdk_runner_drains_query_and_returns_stats() -> None:
    seen: list[dict[str, Any]] = []
    init = SystemMessage(subtype="init", data={"tools": ["Task"]})
    runner = SdkRunner(query_fn=_fake_query([init, _result()], seen))
    options = ClaudeAgentOptions(model="x")
    stats = await runner.run("依頼", options, _collector())
    assert stats.num_turns == 7
    assert seen == [{"prompt": "依頼", "options": options}]


async def test_sdk_runner_without_result_gives_zero_stats() -> None:
    runner = SdkRunner(query_fn=_fake_query([], []))
    assert await runner.run("p", ClaudeAgentOptions(), _collector()) == RunStats()


async def test_sdk_runner_wraps_sdk_errors_with_zero_stats_without_result() -> None:
    cause = ResultError(
        "Reached maximum number of turns (2)", {"subtype": "error_max_turns"}
    )

    async def failing_query(*, prompt: str, options: ClaudeAgentOptions):
        yield SystemMessage(subtype="init", data={})
        raise cause

    runner = SdkRunner(query_fn=failing_query)
    with pytest.raises(RunFailedError) as info:
        await runner.run("p", ClaudeAgentOptions(), _collector())
    assert isinstance(info.value, claude_agent_sdk.ClaudeSDKError)
    assert info.value.cause is cause and info.value.__cause__ is cause
    assert info.value.stats == RunStats()


async def test_sdk_runner_keeps_stats_of_the_error_result() -> None:
    # CLI は is_error の ResultMessage を返してから ResultError を出す（SDK の docstring）
    failed = _result(
        subtype="error_max_turns",
        is_error=True,
        num_turns=30,
        duration_ms=90000,
        total_cost_usd=0.83,
        usage={"input_tokens": 120000, "output_tokens": 9000},
    )

    async def failing_query(*, prompt: str, options: ClaudeAgentOptions):
        yield failed
        raise ResultError(
            "Claude Code returned an error result: Reached maximum number of turns",
            {"subtype": "error_max_turns", "terminal_reason": "max_turns"},
        )

    runner = SdkRunner(query_fn=failing_query)
    with pytest.raises(RunFailedError) as info:
        await runner.run("p", ClaudeAgentOptions(), _collector())
    assert info.value.stats == RunStats(
        duration_ms=90000,
        num_turns=30,
        tokens_in=120000,
        tokens_out=9000,
        cost_usd=0.83,
    )
    assert isinstance(info.value.cause, ResultError)


async def test_sdk_runner_does_not_wrap_other_exceptions() -> None:
    async def broken_query(*, prompt: str, options: ClaudeAgentOptions):
        yield SystemMessage(subtype="init", data={})
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        await SdkRunner(query_fn=broken_query).run(
            "p", ClaudeAgentOptions(), _collector()
        )


def test_collector_needs_an_output_context() -> None:
    with pytest.raises(TypeError):
        RunCollector([1])  # type: ignore[arg-type]


def test_sdk_runner_uses_sdk_query_by_default() -> None:
    assert SdkRunner().query_fn is claude_agent_sdk.query  # 呼ばない（参照だけ）


def test_runners_satisfy_protocol() -> None:
    for runner in (
        SdkRunner(),
        FakeRunner(),
        RaisingRunner(RuntimeError()),
        SlowRunner(0),
    ):
        assert isinstance(runner, AgentRunner)

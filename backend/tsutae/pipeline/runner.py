"""Agent SDK を回す部分（AgentRunner プロトコルと SdkRunner）。

- `SdkRunner` は `claude_agent_sdk.query` を最後まで読み、ResultMessage から RunStats を
  作る。ClaudeSDKError（max_turns の ResultError を含む）は `RunFailedError` に包んで
  上へ出す（振り分けは orchestrator.convert）。CLI は失敗の時も is_error の
  ResultMessage を返してから ResultError を出すので、その費用・トークン数を
  `RunFailedError.stats` に残す（いちばん費用のかかる失敗をログから消さない）
- テストでは `query_fn` に偽物を渡す（実際の API は呼ばない）。FakeRunner は
  backend/tests/pipeline_fakes.py
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Protocol, runtime_checkable

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query

from tsutae.pipeline.tools import RunCollector
from tsutae.schemas import RunStats

__all__ = ["AgentRunner", "RunFailedError", "SdkRunner", "stats_from_result"]

QueryFn = Callable[..., AsyncIterator[Any]]
_USAGE_IN = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
_MODEL_USAGE_IN = ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens")


@runtime_checkable
class AgentRunner(Protocol):
    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats: ...


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(value) or value < 0:
        return 0
    return int(value)


def _cost(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value) if math.isfinite(value) and value >= 0 else 0.0


def _tokens(result: ResultMessage) -> tuple[int, int]:
    """入力側（キャッシュ込み）と出力のトークン数。model_usage があればその合計。"""
    per_model = [
        u for u in (result.model_usage or {}).values() if isinstance(u, Mapping)
    ]
    if per_model:
        tokens_in = sum(_count(u.get(k)) for u in per_model for k in _MODEL_USAGE_IN)
        return tokens_in, sum(_count(u.get("outputTokens")) for u in per_model)
    usage = result.usage if isinstance(result.usage, Mapping) else {}
    return sum(_count(usage.get(k)) for k in _USAGE_IN), _count(
        usage.get("output_tokens")
    )


def stats_from_result(result: ResultMessage | None) -> RunStats:
    if result is None:
        return RunStats()
    tokens_in, tokens_out = _tokens(result)
    return RunStats(
        duration_ms=_count(result.duration_ms),
        num_turns=_count(result.num_turns),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=_cost(result.total_cost_usd),
    )


class RunFailedError(ClaudeSDKError):
    """SDK の失敗（`cause`）に、それまでの ResultMessage から作った RunStats を添えたもの。"""

    def __init__(self, cause: ClaudeSDKError, stats: RunStats) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.stats = stats


class SdkRunner:
    """`claude_agent_sdk.query` で1回の変換を回す。"""

    def __init__(self, query_fn: QueryFn | None = None) -> None:
        self.query_fn: QueryFn = query_fn if query_fn is not None else query

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        result: ResultMessage | None = None
        try:
            async for message in self.query_fn(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result = message
        except ClaudeSDKError as exc:
            raise RunFailedError(exc, stats_from_result(result)) from exc
        return stats_from_result(result)

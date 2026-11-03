"""変換パイプライン（docs/architecture.md §7。Claude Agent SDK）。

- inputs: 今コースの記録を選び、伏せ字を掛けて `PreparedInput` を作る（範囲外は黙って外す）
- prompt / agents / tools / hooks: 主エージェントへの指示、3役、出力の受け口、H1〜H4
- checks: 出力の受け口で、用語・入力から写す項目・per_symptom の結び付きを検査する
- runner / orchestrator: SDK を回し、失敗はフォールバック（`ConversionResult`）にする
- logs: 文面を入れないログ（D5）
"""

from tsutae.pipeline.inputs import (
    REASON_KNOWN_IDENTIFIER,
    PrepareInputError,
    mask_free_text,
    prepare_input,
)
from tsutae.pipeline.logs import EventLogger, MemoryLogger, PipelineLogger
from tsutae.pipeline.orchestrator import (
    ALLOWED_TOOLS,
    DISALLOWED_TOOLS,
    build_options,
    convert,
)
from tsutae.pipeline.runner import AgentRunner, RunFailedError, SdkRunner
from tsutae.pipeline.tools import RunCollector

__all__ = [
    "ALLOWED_TOOLS",
    "DISALLOWED_TOOLS",
    "REASON_KNOWN_IDENTIFIER",
    "AgentRunner",
    "EventLogger",
    "MemoryLogger",
    "PipelineLogger",
    "PrepareInputError",
    "RunCollector",
    "RunFailedError",
    "SdkRunner",
    "build_options",
    "convert",
    "mask_free_text",
    "prepare_input",
]

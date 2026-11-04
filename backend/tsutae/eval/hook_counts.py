"""変換1回で Hook が止めた回数（H1 の block・H2 の deny）。症例は全て合成。

最終の Timeline は H2（引用が伏せ字後の文の部分文字列か）を通ったものなので、
指標5の引用一致率は本番では構造上 100% になる。幻覚引用の量は H2 が拒否した
回数で見る（spec 17.2、decisions「指標5」）。

`HookCounter` は `convert(..., logger=...)` に渡せる EventLogger 互換の受け皿。
event 名と tool_name だけを見て数える（文面は持たない）。tsutae.pipeline は
import しない（名前は pipeline と同じ文字列。テストで照合する）。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from tsutae.schemas import Frozen

H1_BLOCK_EVENT = "hook_h1_block"
H2_DENY_EVENT = "hook_h2_deny"
EMIT_TIMELINE_TOOL = "mcp__tsutae__emit_timeline"  # tsutae.pipeline.tools と同じ


class HookCounts(Frozen):
    h1_blocks: int = Field(default=0, ge=0)
    h2_timeline_denies: int = Field(default=0, ge=0)  # emit_timeline の引用
    h2_report_denies: int = Field(default=0, ge=0)  # emit_report の代表引用

    @property
    def h2_denies(self) -> int:
        return self.h2_timeline_denies + self.h2_report_denies

    def __add__(self, other: HookCounts) -> HookCounts:
        return HookCounts(
            h1_blocks=self.h1_blocks + other.h1_blocks,
            h2_timeline_denies=self.h2_timeline_denies + other.h2_timeline_denies,
            h2_report_denies=self.h2_report_denies + other.h2_report_denies,
        )


class HookCounter:
    """`event(name, **fields)` を受けて H1・H2 の回数を数える（1回の変換ごとに作る）。"""

    def __init__(self) -> None:
        self._h1 = 0
        self._h2_timeline = 0
        self._h2_report = 0

    def event(self, name: str, **fields: Any) -> None:
        if name == H1_BLOCK_EVENT:
            self._h1 += 1
        elif name == H2_DENY_EVENT:
            if fields.get("tool_name") == EMIT_TIMELINE_TOOL:
                self._h2_timeline += 1
            else:
                self._h2_report += 1

    def counts(self) -> HookCounts:
        return HookCounts(
            h1_blocks=self._h1,
            h2_timeline_denies=self._h2_timeline,
            h2_report_denies=self._h2_report,
        )

"""D4 レジメンの Claude の1往復の型（T94。architecture 9c「1往復」）。

- `RegimenChat` プロトコル: `async turn(draft, text) -> TurnResult`。draft は往復の
  始まりの下書きの値（`TurnInput`。DB は持たない）。既定は `chat_sdk.SdkRegimenChat`、
  テストは偽物を渡す
- `TurnResult` は往復の後のフォーム・出どころ・Claude の返答・変えた欄の id・`ask`・
  足した質問の key・回数と費用。反映（generation が同じときだけ）は `chat_turn` が行う
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from tsutae.regimen.form import FieldSources, RegimenForm
from tsutae.schemas import RunStats

__all__ = [
    "AskOut",
    "LibraryItem",
    "RegimenChat",
    "TurnInput",
    "TurnOutcome",
    "TurnResult",
]


def _never_taken(_code: str) -> bool:
    return False


@dataclass(frozen=True)
class LibraryItem:
    """部品集の1問（外した問は入れない）。"""

    key: str
    label: str
    text: str
    answer_type: str


@dataclass(frozen=True)
class TurnInput:
    """往復の始まりの下書き（working にした時の値）。

    history は保存済みの会話の行（chat_json）。code_taken は識別名が既存の Skill・
    別の開いた下書きで使われているか（新規の下書きの basic.code の検査に使う）。
    """

    draft_id: int
    form: RegimenForm
    sources: FieldSources
    history: tuple[dict[str, Any], ...] = ()
    library: tuple[LibraryItem, ...] = ()
    allow_code: bool = False
    code_taken: Callable[[str], bool] = _never_taken


@dataclass(frozen=True)
class AskOut:
    """Claude が先生に聞く1問。画面は field_id の欄を赤枠にし、選択肢を出す。"""

    field_id: str
    question: str
    options: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "question": self.question,
            "options": list(self.options),
        }


@dataclass(frozen=True)
class TurnResult:
    form: RegimenForm
    sources: FieldSources
    reply: str
    changed: tuple[str, ...] = ()
    ask: AskOut | None = None
    proposed: tuple[str, ...] = ()
    stats: RunStats = field(default_factory=RunStats)
    tool_calls: int = 0
    rejected: int = 0


@runtime_checkable
class RegimenChat(Protocol):
    async def turn(self, draft: TurnInput, text: str) -> TurnResult: ...


@dataclass(frozen=True)
class TurnOutcome:
    """往復の後の下書きと、失敗のコード（成功は None）。chat_turn.run_turn の戻り値。"""

    draft: dict[str, Any]
    error: str | None = None

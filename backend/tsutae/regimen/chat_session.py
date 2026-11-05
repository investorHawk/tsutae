"""1往復の間のフォームの受け皿（ChatSession。T94）。

ツール（chat_tools）は DB に書かず、この受け皿の中のフォーム・出どころ・行の ref に
当てる（pipeline の RunCollector と同じ作り）。往復が終わったら `result()` で
`TurnResult` にし、反映（generation が同じときだけ）は chat_turn が行う。時間切れ・例外の
ときは受け皿ごと捨てる（途中の値は残らない）。

1往復の中だけの可変の入れ物なので、`commit` で属性を差し替える（フォーム・出どころ・
行の ref はどれも frozen の値で、差し替えるだけ）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from tsutae.pipeline.logs import EventLogger, MemoryLogger, reason_code
from tsutae.regimen.chat_handles import RowHandles
from tsutae.regimen.chat_types import AskOut, LibraryItem, TurnInput, TurnResult
from tsutae.regimen.form import FieldSources, RegimenForm, field_ids
from tsutae.regimen.text_checks import FieldIssue
from tsutae.schemas import RunStats

__all__ = ["ChatSession", "Reason", "current_logger", "logging_to"]

# (欄の ref, コード, 理由の文)。理由の文に入力の文面は入れない
Reason = tuple[str, str, str]
MAX_REPLY_CHARS = 2000

_LOGGER: ContextVar[EventLogger | None] = ContextVar(
    "tsutae_regimen_chat_logger", default=None
)


@contextmanager
def logging_to(logger: EventLogger) -> Iterator[EventLogger]:
    """この中で動く1往復（Hook・ツール）の記録先を logger にする（contextvars）。

    chat_turn が PipelineLogger(conn, "regimen_chat", draft_id) を設定する。RegimenChat
    プロトコルの引数に無いので、editor の `logging_to` と同じく文脈で渡す。
    """
    token = _LOGGER.set(logger)
    try:
        yield logger
    finally:
        _LOGGER.reset(token)


def current_logger() -> EventLogger:
    """logging_to で設定したロガー。無ければ捨てる（MemoryLogger）。"""
    logger = _LOGGER.get()
    return logger if logger is not None else MemoryLogger()


class ChatSession:
    """1往復のフォーム・出どころ・行の ref と、変えた欄・聞いた問い・回数。"""

    def __init__(self, draft: TurnInput, logger: EventLogger | None = None) -> None:
        self.form: RegimenForm = draft.form
        self.sources: FieldSources = draft.sources
        self.handles: RowHandles = RowHandles.from_form(draft.form)
        self.allow_code: bool = draft.allow_code
        self.code_taken: Callable[[str], bool] = draft.code_taken
        self.library: dict[str, LibraryItem] = {i.key: i for i in draft.library}
        self.logger: EventLogger = logger if logger is not None else current_logger()
        self.changed: list[str] = []
        self.ask: AskOut | None = None
        self.proposed: list[str] = []
        self.tool_calls = 0
        self.rejected = 0

    # -- 回数とログ -----------------------------------------------------------

    def called(self) -> None:
        self.tool_calls += 1

    def log(self, tool_name: str, decision: str) -> None:
        self.logger.event("regimen_tool", tool_name=tool_name, decision=decision)

    def reject(self, tool_name: str, reasons: list[Reason]) -> None:
        self.rejected += 1
        self.log(tool_name, reason_code("reject", reasons[0][1]))

    # -- 欄 ------------------------------------------------------------------

    def is_protected(self, field_id: str) -> bool:
        """先生が直接入れた欄（doctor_edit）か。"""
        return self.sources.root.get(field_id) == "doctor_edit"

    def row_protected(self, section: str, row_id: str) -> bool:
        prefix = f"{section}.{row_id}."
        return any(
            fid.startswith(prefix) and src == "doctor_edit"
            for fid, src in self.sources.root.items()
        )

    def issue_reasons(
        self, issues: Iterable[FieldIssue], handles: RowHandles
    ) -> list[Reason]:
        """検査の FieldIssue（欄の id）を ref の理由に直す。"""
        return [(handles.ref(i.field_id), i.code, i.message) for i in issues]

    def commit(
        self,
        form: RegimenForm,
        sources: FieldSources,
        handles: RowHandles,
        changed: Iterable[str],
    ) -> None:
        self.form = form
        self.sources = sources
        self.handles = handles
        for field_id in changed:
            if field_id not in self.changed:
                self.changed.append(field_id)

    # -- 結果 ----------------------------------------------------------------

    def result(self, reply: str, stats: RunStats) -> TurnResult:
        """往復の結果。変えた欄は今のフォームに残っているものだけ。"""
        known = set(field_ids(self.form))
        return TurnResult(
            form=self.form,
            sources=self.sources,
            reply=reply.strip()[:MAX_REPLY_CHARS],
            changed=tuple(fid for fid in self.changed if fid in known),
            ask=self.ask,
            proposed=tuple(self.proposed),
            stats=stats,
            tool_calls=self.tool_calls,
            rejected=self.rejected,
        )

"""出力の受け口（カスタムツール emit_timeline / emit_report）と RunCollector。

- 主エージェントはこの2つのツールでだけ結果を渡す（サブエージェントはツールを持たない）
- input_schema は pydantic から作った JSON Schema。SDK は handler の前に jsonschema で
  検査するので、型の誤りはそこで返ることがある。handler では pydantic で検査し直し、
  続けて入力と用語の一覧に照らす（checks.py: 用語・question_key・入力から写す項目・
  記録日以前の date・重複・食い違いのクローズ回答・per_symptom の行の過不足）。失敗は
  `is_error` で「項目名つきの短い理由（写す値・数える値は期待される値つき）」を返して
  モデルに直させる（自由記載の文面・用語名は返さない）
- per_symptom の並び順は拒否しない。受け付けた行を (start_date, term) で並べ直して持つ
  （term 名の文字列順はモデルが再現しにくい。checks.py の docstring）
- input_schema は pydantic の schema の複製に、項目ごとの description を足したもの
  （モデルが項目の決まりをツールの定義から読めるように。元の schema は書き換えない）
- 引用（source_quote 等）の原文一致は Hook H2 が見る。ここでは見ない
- emit_report は受け付けた timeline が無ければ拒否する。後から別の timeline を受け付けて
  picks が結び付かなくなったら picks を捨てる（もう一度 emit_report を呼ばせる）
- 何度呼ばれても、検査に通った最後のものを採用する
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool
from pydantic import Field, ValidationError

from tsutae.pipeline.checks import (
    OutputContext,
    report_problems,
    sort_per_symptom,
    timeline_problems,
)
from tsutae.pipeline.logs import EventLogger, reason_code
from tsutae.schemas import (
    Contradiction,
    Frozen,
    PreparedInput,
    ReportPicks,
    SymptomSummary,
    Timeline,
    TimelineEvent,
)

__all__ = [
    "EMIT_REPORT",
    "EMIT_REPORT_SCHEMA",
    "EMIT_REPORT_TOOL",
    "EMIT_TIMELINE",
    "EMIT_TIMELINE_SCHEMA",
    "EMIT_TIMELINE_TOOL",
    "SERVER_NAME",
    "EmitReportArgs",
    "EmitTimelineArgs",
    "RunCollector",
    "build_server",
    "build_tools",
    "handle_emit_report",
    "handle_emit_timeline",
]

SERVER_NAME = "tsutae"
EMIT_TIMELINE = "emit_timeline"
EMIT_REPORT = "emit_report"
EMIT_TIMELINE_TOOL = f"mcp__{SERVER_NAME}__{EMIT_TIMELINE}"
EMIT_REPORT_TOOL = f"mcp__{SERVER_NAME}__{EMIT_REPORT}"
MAX_REASONS = 20


class EmitTimelineArgs(Frozen):
    events: list[TimelineEvent]
    contradictions: list[Contradiction] = Field(default_factory=list)


class EmitReportArgs(Frozen):
    per_symptom: list[SymptomSummary]


_QUOTE = (
    "その entry_no の記録の masked_free_text の部分文字列を一字も変えずに写す"
    "（句読点・空白・改行・全角半角・伏せ字も同じ。要約・つなぎ合わせをしない）"
)
_FIELD_DESCRIPTIONS: Mapping[str, Mapping[str, str]] = {
    "TimelineEvent": {
        "entry_no": "入力の entries の entry_no（masked_free_text のある記録だけ）",
        "date": "出来事の暦日 YYYY-MM-DD。その記録の record_date 以前",
        "day": (
            "date を依頼文の日付と Day の対応表で引いた Day（自分で数えない）。"
            "day1_date より前は null。null でも省かない"
        ),
        "course_no": "schedule.course_no をそのまま",
        "term": "用語の一覧（CTCAE v5.0 JCOG版）の用語名をそのまま",
        "question_key": (
            "用語の一覧でその term に対応する key。入力の questions に無い key なら null"
        ),
        "status": "present（あり）・improving（改善中）・absent（否定）",
        "source_quote": _QUOTE,
        "confidence": "0〜1。日付や用語に迷ったら低く",
        "recalled": "date が record_date より前なら true、同じ日なら false",
        "by_proxy": "その記録の by_proxy をそのまま",
    },
    "Contradiction": {
        "entry_no": "answers と masked_free_text の両方がある記録の entry_no",
        "date": "その記録の record_date をそのまま",
        "day": "その記録の day をそのまま（null でも省かない）",
        "question_key": "その記録の answers にある question_key",
        "closed_answer": "その記録の answers のその質問の value をそのまま",
        "free_text_quote": _QUOTE,
    },
    "SymptomSummary": {
        "term": "受け付けた events の present か improving の term",
        "question_key": "その term の出来事の question_key",
        "start_day": (
            "その term の present か improving の出来事で date が最も早いものの day"
            "（null でも省かない）"
        ),
        "start_date": "その term の present か improving の出来事で最も早い date",
        "representative_quote": (
            "その term の present か improving の出来事のどれか1つの source_quote を"
            "丸ごとそのまま"
        ),
        "confidence": "representative_quote に選んだ出来事の confidence をそのまま",
    },
}


def _described(schema: Mapping[str, Any]) -> dict[str, Any]:
    """schema の複製の $defs の項目に description を足す（元は書き換えない）。"""
    out = copy.deepcopy(dict(schema))
    for name, fields in _FIELD_DESCRIPTIONS.items():
        props = out.get("$defs", {}).get(name, {}).get("properties", {})
        for field_name, text in fields.items():
            if field_name in props:
                props[field_name]["description"] = text
    return out


EMIT_TIMELINE_SCHEMA: dict[str, Any] = _described(EmitTimelineArgs.model_json_schema())
EMIT_REPORT_SCHEMA: dict[str, Any] = _described(EmitReportArgs.model_json_schema())

_RESEND = (
    "エラーや拒否が返ったら何も受け付けていない。理由に挙がった項目を直し、全体を"
    "もう一度渡す"
)
_TIMELINE_DESCRIPTION = (
    "変換した時系列を渡す。入力は {events: TimelineEvent[], contradictions: "
    "Contradiction[]}。項目は schema にあるものだけ（足さない。day は null でも省かない）。"
    "引用は masked_free_text の部分文字列そのまま。term は用語の一覧の名前そのもの、"
    "course_no・by_proxy・食い違いの question_key・closed_answer・date・day は入力から"
    "写す。events の day は依頼文の日付と Day の対応表で date を引く。date は記録の "
    "record_date 以前。同じ出来事・同じ食い違いは重ねない。" + _RESEND
)
_REPORT_DESCRIPTION = (
    "レポートの症状別の時系列を渡す。入力は {per_symptom: SymptomSummary[]}。"
    "emit_timeline が受け付けられた後に呼ぶ。term・question_key は受け付けた events"
    "（present か improving）のもの、start_date・start_day はその term の present か "
    "improving の出来事で date が最も早いもののもの、representative_quote・confidence は"
    "その term の present か improving の出来事の1つの source_quote・confidence を丸ごと"
    "そのまま。present か improving の term ごとにちょうど1行（省かない・足さない）。"
    "並びは開始 Day の早い順でよい（受け付けた後に並べ直すので、順序では拒否しない）。"
    + _RESEND
)


class RunCollector:
    """1回の変換の受け皿。検査に通った最後の timeline と picks を持つ。"""

    def __init__(self, context: OutputContext, logger: EventLogger | None = None):
        if not isinstance(context, OutputContext):
            raise TypeError("RunCollector は OutputContext から作る（from_prepared）")
        self._context = context
        self._logger = logger
        self._timeline: Timeline | None = None
        self._picks: ReportPicks | None = None
        self.timeline_calls = 0
        self.report_calls = 0

    @classmethod
    def from_prepared(
        cls, prepared: PreparedInput, logger: EventLogger | None = None
    ) -> RunCollector:
        return cls(OutputContext.from_prepared(prepared), logger=logger)

    @property
    def context(self) -> OutputContext:
        return self._context

    @property
    def entry_nos(self) -> frozenset[int]:
        return self._context.entry_nos

    @property
    def timeline(self) -> Timeline | None:
        return self._timeline

    @property
    def picks(self) -> ReportPicks | None:
        return self._picks

    def accept_timeline(self, args: EmitTimelineArgs) -> bool:
        """timeline を差し替える。結び付かなくなった picks を捨てたら True。"""
        self._timeline = Timeline(
            events=list(args.events), contradictions=list(args.contradictions)
        )
        if self._picks is None or not report_problems(
            self._picks.per_symptom, self._timeline
        ):
            return False
        self._picks = None
        self.log(EMIT_REPORT, "drop:stale")
        return True

    def accept_picks(self, args: EmitReportArgs) -> None:
        self._picks = ReportPicks(per_symptom=sort_per_symptom(args.per_symptom))

    def log(self, event: str, decision: str) -> None:
        if self._logger is not None:
            tool_name = (
                EMIT_TIMELINE_TOOL if event == EMIT_TIMELINE else EMIT_REPORT_TOOL
            )
            self._logger.event(event, tool_name=tool_name, decision=decision)


def _loc(parts: Iterable[object]) -> str:
    return ".".join(str(p) for p in parts) or "(root)"


def _error(reasons: list[tuple[str, str]], headline: str) -> dict[str, Any]:
    shown = [f"{where}: {msg}" for where, msg in reasons[:MAX_REASONS]]
    if len(reasons) > MAX_REASONS:
        shown.append(f"ほか {len(reasons) - MAX_REASONS} 件")
    text = (
        f"{headline}（何も受け付けていない）。挙げた項目を直し、全体をもう一度渡す: "
        + "; ".join(shown)
    )
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _schema_reasons(exc: ValidationError) -> list[tuple[str, str]]:
    return [
        (_loc(err["loc"]), err["msg"])
        for err in exc.errors(include_input=False, include_url=False)
    ]


def _validate(
    model: type[EmitTimelineArgs] | type[EmitReportArgs], args: object
) -> tuple[Any, list[tuple[str, str]]]:
    if not isinstance(args, dict):
        return None, [("(root)", "オブジェクトで渡す")]
    try:
        return model.model_validate(args), []
    except ValidationError as exc:
        return None, _schema_reasons(exc)


def handle_emit_timeline(
    args: dict[str, Any], collector: RunCollector
) -> dict[str, Any]:
    """emit_timeline の本体。検査に通れば collector に保存する。"""
    collector.timeline_calls += 1
    parsed, reasons = _validate(EmitTimelineArgs, args)
    if parsed is not None:
        reasons = timeline_problems(
            parsed.events, parsed.contradictions, collector.context
        )
    if reasons:
        collector.log(EMIT_TIMELINE, reason_code("reject", reasons[0][0]))
        return _error(reasons, "emit_timeline の入力が違う")
    dropped = collector.accept_timeline(parsed)
    collector.log(EMIT_TIMELINE, "accept")
    text = (
        f"受け付けた: events {len(parsed.events)}件、"
        f"contradictions {len(parsed.contradictions)}件"
    )
    if dropped:
        text += "。前の emit_report はこの events と合わないので、もう一度 emit_report を呼ぶ"
    return _ok(text)


def handle_emit_report(args: dict[str, Any], collector: RunCollector) -> dict[str, Any]:
    """emit_report の本体。受け付けた timeline と結び付けば collector に保存する。"""
    collector.report_calls += 1
    parsed, reasons = _validate(EmitReportArgs, args)
    if parsed is not None:
        reasons = report_problems(parsed.per_symptom, collector.timeline)
    if reasons:
        collector.log(EMIT_REPORT, reason_code("reject", reasons[0][0]))
        return _error(reasons, "emit_report の入力が違う")
    collector.accept_picks(parsed)
    collector.log(EMIT_REPORT, "accept")
    return _ok(f"受け付けた: per_symptom {len(parsed.per_symptom)}件")


def build_tools(collector: RunCollector) -> list[SdkMcpTool[Any]]:
    """collector を閉じ込めた2つのツール（SDK の @tool）。"""

    @tool(EMIT_TIMELINE, _TIMELINE_DESCRIPTION, EMIT_TIMELINE_SCHEMA)
    async def emit_timeline(args: dict[str, Any]) -> dict[str, Any]:
        return handle_emit_timeline(args, collector)

    @tool(EMIT_REPORT, _REPORT_DESCRIPTION, EMIT_REPORT_SCHEMA)
    async def emit_report(args: dict[str, Any]) -> dict[str, Any]:
        return handle_emit_report(args, collector)

    return [emit_timeline, emit_report]


def build_server(collector: RunCollector) -> McpSdkServerConfig:
    """名前 `tsutae` の SDK MCP サーバー（ツール emit_timeline・emit_report）。"""
    return create_sdk_mcp_server(SERVER_NAME, tools=build_tools(collector))

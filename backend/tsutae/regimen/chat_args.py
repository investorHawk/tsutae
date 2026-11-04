"""D4 レジメンの Claude のツールの名前・入力の形（pydantic）・説明（T94）。

ツールは同一プロセスの SDK MCP サーバー `tsutae_regimen` の3つ:

- `set_fields`: 欄の値を変える（`changes`・`add_rows`・`delete_rows`・
  `overwrite_requested`）。出どころは doctor_text（先生の文から）か standard（標準の値）
- `ask`: 先生に1問聞く（欄の ref・問い・選択肢 2〜4）
- `propose_questions`: 患者への質問を足す（部品集の key か新しい3択の質問）

行と欄は ref（`drugs.1`・`drugs.1.days`。chat_handles）で指す。input_schema は pydantic の
schema。SDK が handler の前に jsonschema で見るが、handler でも pydantic で検査し直す。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictStr

__all__ = [
    "ASK",
    "ASK_TOOL",
    "AskArgs",
    "FieldValue",
    "NewQuestion",
    "PROPOSE_QUESTIONS",
    "PROPOSE_QUESTIONS_TOOL",
    "ProposeQuestionsArgs",
    "SERVER_NAME",
    "SET_FIELDS",
    "SET_FIELDS_TOOL",
    "SetFieldsArgs",
    "TOOL_DESCRIPTIONS",
    "tool_schema",
]

SERVER_NAME = "tsutae_regimen"
SET_FIELDS = "set_fields"
ASK = "ask"
PROPOSE_QUESTIONS = "propose_questions"
SET_FIELDS_TOOL = f"mcp__{SERVER_NAME}__{SET_FIELDS}"
ASK_TOOL = f"mcp__{SERVER_NAME}__{ASK}"
PROPOSE_QUESTIONS_TOOL = f"mcp__{SERVER_NAME}__{PROPOSE_QUESTIONS}"

MAX_CHANGES = 100
MAX_ROWS = 30
MAX_REF = 60
MAX_ASK_QUESTION = 200
MAX_ASK_OPTION = 40
MAX_PROPOSALS = 10

AiSource = Literal["doctor_text", "standard"]
# ref・key の並びの1つ（拒否の理由に Claude が書いた ref がそのまま戻るので長さを止める）
Ref = Annotated[StrictStr, Field(max_length=MAX_REF)]


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class FieldValue(_Args):
    field: StrictStr = Field(max_length=MAX_REF)
    value: JsonValue
    source: AiSource


class SetFieldsArgs(_Args):
    changes: list[FieldValue] = Field(default_factory=list, max_length=MAX_CHANGES)
    add_rows: list[Ref] = Field(default_factory=list, max_length=MAX_ROWS)
    delete_rows: list[Ref] = Field(default_factory=list, max_length=MAX_ROWS)
    overwrite_requested: StrictBool = False


class AskArgs(_Args):
    field: StrictStr = Field(max_length=MAX_REF)
    question: StrictStr = Field(min_length=1, max_length=MAX_ASK_QUESTION)
    options: list[StrictStr] = Field(min_length=2, max_length=4)


class NewQuestion(_Args):
    key: StrictStr = Field(max_length=60)
    label: StrictStr = Field(max_length=60)
    text: StrictStr = Field(max_length=300)


class ProposeQuestionsArgs(_Args):
    from_library: list[Ref] = Field(default_factory=list, max_length=MAX_PROPOSALS)
    new_questions: list[NewQuestion] = Field(
        default_factory=list, max_length=MAX_PROPOSALS
    )
    source: AiSource = "standard"


_SCHEMA_MODELS: dict[str, type[_Args]] = {
    SET_FIELDS: SetFieldsArgs,
    ASK: AskArgs,
    PROPOSE_QUESTIONS: ProposeQuestionsArgs,
}

_RESEND = "エラーや拒否が返ったら何も受け付けていない。理由の欄を直してもう一度渡す。"
TOOL_DESCRIPTIONS: dict[str, str] = {
    SET_FIELDS: (
        "フォームの欄の値を変える。changes は {field: 欄の ref（例 drugs.1.days・"
        "basic.cycle_days・notes）, value, source}。source は先生の文から取った値なら "
        "doctor_text、先生の文に無い標準の値なら standard。行を足すときは add_rows に"
        "新しい ref（例 drugs.5）、消すときは delete_rows に ref。先生が直接入れた欄は、"
        "先生が頼んだときだけ overwrite_requested=true で変える。薬の量は入れない。"
        + _RESEND
    ),
    ASK: (
        "決められないことを先生に1問だけ聞く。field は聞きたい欄の ref（行が無ければ "
        "drugs などの節の名前）、question は短い問い、options は選択肢 2〜4 個。"
        "1往復に1回だけ。聞いたら返答の文で伝えて終える。" + _RESEND
    ),
    PROPOSE_QUESTIONS: (
        "患者への質問を足す。from_library は部品集の key、new_questions は部品集に無い"
        "新しい3択の質問 {key, label（短い名前）, text（患者が読む文）}。source は既定 "
        "standard（先生が文で質問を指定したときだけ doctor_text）。" + _RESEND
    ),
}


def tool_schema(name: str) -> dict[str, Any]:
    """ツールの input_schema（pydantic の JSON Schema）。"""
    return _SCHEMA_MODELS[name].model_json_schema()

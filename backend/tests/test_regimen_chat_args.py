"""tsutae.regimen.chat_args: ツールの入力の長さの上限（T94 の確かめ直し）。

ref の並び（add_rows・delete_rows・from_library）の要素にも長さの上限（MAX_REF）を付ける。
拒否の理由には Claude が書いた ref がそのまま戻るので、長い ref は pydantic で止める。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from tsutae.regimen.chat_args import (
    MAX_REF,
    PROPOSE_QUESTIONS,
    SET_FIELDS,
    ProposeQuestionsArgs,
    SetFieldsArgs,
    tool_schema,
)
from tsutae.regimen.chat_session import ChatSession
from tsutae.regimen.chat_tools import handle_set_fields
from tsutae.regimen.chat_types import TurnInput
from tsutae.regimen.form import FieldSources
from tsutae.regimen.source import new_draft_form

LONG = "drugs." + "9" * MAX_REF


@pytest.mark.parametrize(
    "model, args",
    [
        (SetFieldsArgs, {"add_rows": [LONG]}),
        (SetFieldsArgs, {"delete_rows": [LONG]}),
        (ProposeQuestionsArgs, {"from_library": ["k" * (MAX_REF + 1)]}),
    ],
)
def test_ref_lists_have_a_length_limit(model: Any, args: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(args)


def test_schema_has_the_item_limit() -> None:
    props = tool_schema(SET_FIELDS)["properties"]
    for name in ("add_rows", "delete_rows"):
        assert props[name]["items"]["maxLength"] == MAX_REF
    library = tool_schema(PROPOSE_QUESTIONS)["properties"]["from_library"]
    assert library["items"]["maxLength"] == MAX_REF


def test_long_ref_is_not_echoed_back() -> None:
    session = ChatSession(
        TurnInput(draft_id=1, form=new_draft_form(), sources=FieldSources({}))
    )
    result = handle_set_fields({"add_rows": ["drugs." + "9" * 5000]}, session)
    assert result["is_error"] is True
    assert len(result["content"][0]["text"]) < 1000

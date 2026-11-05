"""tsutae.regimen.chat_handles: 依頼文の行の ref（`drugs.1`）と row_id の対応。

row_id（`q-fever`・`d-fu-pump` など）は H1 の id_like に掛かるので、依頼文とツールでは
節＋番号の ref で行を指す（1往復の間だけの対応）。
"""

from __future__ import annotations

import pytest
from regimen_fixtures import extra_form

from tsutae.masking import detect_identifiers
from tsutae.regimen.chat_handles import (
    RowHandles,
    form_view,
    new_row_id,
    sources_view,
)
from tsutae.regimen.form import FieldSources, load_builtin_form


def test_refs_follow_row_order() -> None:
    form = load_builtin_form("regimen-folfox")
    handles = RowHandles.from_form(form)
    assert handles.row_id("drugs.1") == "d-oxaliplatin"
    assert handles.row_id("drugs.4") == "d-fu-pump"
    assert handles.row_id("questions.5") == "q-fever"
    assert handles.row_id("drugs.5") is None
    assert handles.row_id("drugs.0") is None
    assert handles.ref_of_row("side_effects", "se-fever") == "side_effects.5"


def test_field_id_and_ref_roundtrip() -> None:
    handles = RowHandles.from_form(load_builtin_form("regimen-folfox"))
    assert handles.field_id("drugs.4.days") == "drugs.d-fu-pump.days"
    assert handles.field_id("basic.cycle_days") == "basic.cycle_days"
    assert handles.field_id("notes") == "notes"
    assert handles.ref("drugs.d-fu-pump.days") == "drugs.4.days"
    assert handles.ref("questions.q-fever") == "questions.5"
    assert handles.ref("basic.code") == "basic.code"
    assert handles.ref("drugs") == "drugs"


@pytest.mark.parametrize(
    "ref",
    [
        "drugs.9.days",  # 無い行
        "drugs.1.color",  # 無い欄
        "basic.prose",
        "prose",
        "drugs.d-oxaliplatin.days",  # row_id では指せない
        "drugs.1",
        "",
    ],
)
def test_unknown_refs(ref: str) -> None:
    handles = RowHandles.from_form(load_builtin_form("regimen-folfox"))
    assert handles.field_id(ref) is None


def test_bind_returns_new_handles() -> None:
    form = load_builtin_form("regimen-capox")
    handles = RowHandles.from_form(form)
    added = handles.bind("drugs.9", "drug1")
    assert added.row_id("drugs.9") == "drug1"
    assert handles.row_id("drugs.9") is None  # 元は変えない
    removed = added.unbind("drugs.9")
    assert removed.row_id("drugs.9") is None
    # 一度使った ref は同じ往復の中で使い回さない
    assert not removed.is_free("drugs.9")
    assert handles.is_free("drugs.9")
    assert not handles.is_free("drugs.1")
    assert not handles.is_free("drugs.100")
    assert not handles.is_free("notes.1")


def test_new_row_id_is_unique_and_h1_safe() -> None:
    form = extra_form("ram_wptx")
    rid = new_row_id("questions", form, taken=frozenset())
    assert rid == "question1"
    assert new_row_id("questions", form, taken=frozenset({"question1"})) == (
        "question2"
    )
    assert new_row_id("drugs", form, taken=frozenset()) == "drug1"
    assert new_row_id("side_effects", form, taken=frozenset()) == "effect1"
    assert detect_identifiers(rid) == []


@pytest.mark.parametrize("name", ["regimen-folfox", "regimen-capox"])
def test_form_view_has_no_row_ids(name: str) -> None:
    form = load_builtin_form(name)
    handles = RowHandles.from_form(form)
    view = form_view(form, handles)
    text = repr(view)
    for row in [*form.drugs, *form.side_effects, *form.questions]:
        assert row.row_id not in text
    assert "prose" not in view
    assert view["drugs"][0]["ref"] == "drugs.1"
    assert view["basic"]["code"] == form.basic.code
    assert detect_identifiers(text) == []


def test_sources_view_uses_refs() -> None:
    form = load_builtin_form("regimen-folfox")
    handles = RowHandles.from_form(form)
    sources = FieldSources(
        {"drugs.d-fu-pump.days": "doctor_edit", "basic.target": "standard"}
    )
    assert sources_view(sources, handles) == {
        "drugs.4.days": "doctor_edit",
        "basic.target": "standard",
    }

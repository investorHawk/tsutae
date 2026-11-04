"""RegimenForm・欄の id・出どころ（T91。architecture 9c）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from regimen_fixtures import EXTRA_REGIMENS, extra_form

from tsutae.regimen import (
    BUILTIN_FORMS_DIR,
    DayRange,
    FieldSources,
    RegimenForm,
    field_ids,
    load_builtin_form,
    load_form_json,
    prune_sources,
    unknown_source_ids,
)


def test_builtin_forms_exist_for_folfox_and_capox() -> None:
    assert sorted(p.name for p in BUILTIN_FORMS_DIR.glob("*.json")) == [
        "capox.json",
        "folfox.json",
    ]
    assert load_builtin_form("regimen-folfox").basic.code == "FOLFOX"
    assert load_builtin_form("regimen-capox").basic.code == "CAPOX"


@pytest.mark.parametrize("name", ["regimen-xelox", "../x", "report-format-default"])
def test_unknown_builtin_form(name: str) -> None:
    with pytest.raises(KeyError):
        load_builtin_form(name)


def test_form_is_frozen_and_forbids_extra() -> None:
    form = extra_form("ram_wptx")
    with pytest.raises(ValidationError):
        form.basic.cycle_days = 21  # type: ignore[misc]
    data = EXTRA_REGIMENS["ram_wptx"]()
    data["dose"] = "80mg"
    with pytest.raises(ValidationError):
        RegimenForm.model_validate(data)


def test_form_is_strict() -> None:
    data = EXTRA_REGIMENS["ram_wptx"]()
    data["basic"]["cycle_days"] = "28"
    with pytest.raises(ValidationError):
        RegimenForm.model_validate(data)


def test_form_json_round_trip() -> None:
    form = load_builtin_form("regimen-capox")
    assert load_form_json(form.model_dump_json()) == form


def test_day_range() -> None:
    assert DayRange(start=1, end=5).model_dump() == {"start": 1, "end": 5}


def test_field_ids_follow_row_ids() -> None:
    ids = field_ids(extra_form("lonsurf_bv"))
    assert ids[:4] == (
        "basic.display_name",
        "basic.code",
        "basic.target",
        "basic.cycle_days",
    )
    for fid in (
        "drugs.d-ftd.name",
        "drugs.d-ftd.route",
        "drugs.d-ftd.days",
        "drugs.d-ftd.times_per_day",
        "drugs.d-ftd.start_note",
        "side_effects.se-fatigue.phrases",
        "side_effects.se-fatigue.ctcae_terms",
        "side_effects.se-fatigue.question_key",
        "questions.q-fever.key",
        "questions.q-fever.label",
        "questions.q-fever.text",
        "questions.q-fever.answer_type",
        "notes",
    ):
        assert fid in ids
    assert len(ids) == len(set(ids))
    assert not any("prose" in fid for fid in ids)


def test_field_sources_accept_only_known_kinds() -> None:
    sources = FieldSources({"basic.code": "standard", "notes": "doctor_edit"})
    assert sources.root["basic.code"] == "standard"
    with pytest.raises(ValidationError):
        FieldSources({"basic.code": "claude"})


def test_unknown_source_ids_and_prune() -> None:
    form = extra_form("ram_wptx")
    sources = FieldSources(
        {
            "basic.cycle_days": "doctor_text",
            "drugs.d-gone.days": "standard",
            "drugs.d-ram.days": "standard",
        }
    )
    assert unknown_source_ids(form, sources) == ["drugs.d-gone.days"]
    pruned = prune_sources(form, sources)
    assert pruned.root == {
        "basic.cycle_days": "doctor_text",
        "drugs.d-ram.days": "standard",
    }
    assert "drugs.d-gone.days" in sources.root  # 元は変えない

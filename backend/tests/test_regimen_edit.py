"""フォームの直接編集（`apply_patch`。PATCH .../fields と T94 の set_fields が使う）。

- 欄の id は `field_ids` の形（`basic.cycle_days`・`drugs.<row_id>.days`・`notes`）
- 行の削除（`drugs.<row_id>`）→ 行の追加 → 欄の変更 の順。元のフォームは変えない
- 変えた欄の出どころを付ける（既定 doctor_edit）。空にした欄・消した行の出どころは外す
- 未知の欄・型の違い・validate_form（H1・薬の量など）に掛かれば RegimenFormError（欄の id）
- 識別名は allow_code のときだけ。体温の質問は消せない
"""

from __future__ import annotations

import pytest
from regimen_fixtures import extra_form

from tsutae.regimen import FieldSources, RegimenFormError, load_builtin_form
from tsutae.regimen.edit import FieldChange, FormPatch, RowAdd, apply_patch

EMPTY = FieldSources({})


def _codes(exc: pytest.ExceptionInfo[RegimenFormError]) -> set[tuple[str, str]]:
    return {(i.field_id, i.code) for i in exc.value.issues}


def test_change_sets_value_and_source() -> None:
    form = extra_form("folfiri_bv")
    patch = FormPatch(changes=(FieldChange("drugs.d-bv.name", "ベバシズマブ（BV）"),))
    new, sources = apply_patch(form, EMPTY, patch)
    assert new.drugs[0].name == "ベバシズマブ（BV）"
    assert form.drugs[0].name == "ベバシズマブ"  # 元は変えない
    assert sources.root == {"drugs.d-bv.name": "doctor_edit"}


def test_change_with_other_source() -> None:
    form = extra_form("folfiri_bv")
    patch = FormPatch(changes=(FieldChange("basic.target", "結腸がん"),))
    _new, sources = apply_patch(form, EMPTY, patch, source="standard")
    assert sources.root == {"basic.target": "standard"}


def test_days_and_numbers() -> None:
    form = extra_form("lonsurf_bv")
    patch = FormPatch(
        changes=(
            FieldChange("drugs.d-ftd.days", [{"start": 1, "end": 5}]),
            FieldChange("drugs.d-ftd.times_per_day", 1),
        )
    )
    new, _ = apply_patch(form, EMPTY, patch)
    assert [(r.start, r.end) for r in new.drugs[0].days] == [(1, 5)]
    assert new.drugs[0].times_per_day == 1


def test_clearing_removes_source() -> None:
    form = extra_form("folfiri_bv")
    sources = FieldSources({"basic.target": "standard", "notes": "doctor_text"})
    patch = FormPatch(
        changes=(FieldChange("basic.target", ""), FieldChange("notes", ""))
    )
    new, out = apply_patch(form, sources, patch)
    assert new.basic.target is None and new.notes == ""
    assert out.root == {}


def test_delete_and_add_rows() -> None:
    form = extra_form("folfiri_bv")
    sources = FieldSources({"side_effects.se-bleeding.phrases": "standard"})
    patch = FormPatch(
        deletes=("side_effects.se-bleeding",),
        adds=(RowAdd("drugs", "d-new"),),
        changes=(
            FieldChange("drugs.d-new.name", "テスト薬"),
            FieldChange("drugs.d-new.route", "infusion"),
            FieldChange("drugs.d-new.days", [{"start": 1, "end": 1}]),
        ),
    )
    new, out = apply_patch(form, sources, patch)
    assert "se-bleeding" not in [r.row_id for r in new.side_effects]
    assert new.drugs[-1].row_id == "d-new" and new.drugs[-1].route == "infusion"
    assert out.root == {
        "drugs.d-new.name": "doctor_edit",
        "drugs.d-new.route": "doctor_edit",
        "drugs.d-new.days": "doctor_edit",
    }


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        (
            FormPatch(changes=(FieldChange("basic.nope", 1),)),
            ("basic.nope", "unknown_field"),
        ),
        (FormPatch(changes=(FieldChange("prose", {}),)), ("prose", "unknown_field")),
        (
            FormPatch(changes=(FieldChange("drugs.d-x.name", "a"),)),
            ("drugs.d-x.name", "unknown_field"),
        ),
        (FormPatch(deletes=("drugs.d-x",)), ("drugs.d-x", "unknown_row")),
        (FormPatch(deletes=("basic",)), ("basic", "unknown_row")),
        (FormPatch(adds=(RowAdd("drugs", "d-bv"),)), ("drugs.d-bv", "row_exists")),
        (FormPatch(adds=(RowAdd("basic", "x"),)), ("basic.x", "unknown_section")),
        (FormPatch(adds=(RowAdd("drugs", "BAD ID"),)), ("drugs", "row_id")),
        (
            FormPatch(changes=(FieldChange("basic.cycle_days", "14"),)),
            ("basic.cycle_days", "type"),
        ),
        (
            FormPatch(changes=(FieldChange("drugs.d-bv.days", [{"start": 1}]),)),
            ("drugs.d-bv.days", "type"),
        ),
        (
            FormPatch(changes=(FieldChange("basic.cycle_days", 99),)),
            ("basic.cycle_days", "out_of_range"),
        ),
        (
            FormPatch(changes=(FieldChange("drugs.d-bv.name", "ベバシズマブ 5mg/kg"),)),
            ("drugs.d-bv.name", "dose"),
        ),
        (
            FormPatch(changes=(FieldChange("notes", "連絡は 090-1234-5678 へ"),)),
            ("notes", "identifier"),
        ),
        (
            FormPatch(changes=(FieldChange("basic.code", "FOLFIRI-X"),)),
            ("basic.code", "code_locked"),
        ),
        (
            FormPatch(deletes=("questions.q-fever",)),
            ("questions", "temperature_required"),
        ),
        (
            FormPatch(
                changes=(FieldChange("questions.q-fever.answer_type", "three_level"),)
            ),
            ("questions", "temperature_required"),
        ),
    ],
)
def test_rejected(patch: FormPatch, expected: tuple[str, str]) -> None:
    form = extra_form("folfiri_bv")
    with pytest.raises(RegimenFormError) as exc:
        apply_patch(form, EMPTY, patch)
    assert expected in _codes(exc)


def test_code_allowed_for_new_drafts() -> None:
    form = extra_form("folfiri_bv")
    patch = FormPatch(changes=(FieldChange("basic.code", "FOLFIRI-X"),))
    new, _ = apply_patch(form, EMPTY, patch, allow_code=True)
    assert new.basic.code == "FOLFIRI-X"


def test_prose_is_kept() -> None:
    form = load_builtin_form("regimen-folfox")
    patch = FormPatch(changes=(FieldChange("notes", "施設の決まり"),))
    new, _ = apply_patch(form, EMPTY, patch)
    assert new.prose == form.prose and new.notes == "施設の決まり"


def test_empty_patch_returns_same_values() -> None:
    form = extra_form("ram_wptx")
    new, sources = apply_patch(form, FieldSources({"notes": "standard"}), FormPatch())
    assert new == form and sources.root == {"notes": "standard"}


# --- 確認の画面の「削除」が送る形（画面の deletePatchOf と対になる） --------------------


def test_deleting_a_referenced_question_alone_is_rejected() -> None:
    form = extra_form("folfiri_bv")
    with pytest.raises(RegimenFormError) as exc:
        apply_patch(form, EMPTY, FormPatch(deletes=("questions.q-diarrhea",)))
    assert _codes(exc) == {
        ("side_effects.se-diarrhea.question_key", "unknown_question")
    }


def test_deleting_a_question_with_its_references_in_one_patch() -> None:
    form = extra_form("folfiri_bv")
    ref = "side_effects.se-diarrhea.question_key"
    sources = FieldSources({ref: "standard", "questions.q-diarrhea.key": "standard"})
    patch = FormPatch(
        deletes=("questions.q-diarrhea",),
        changes=(FieldChange(ref, None),),
    )
    new, updated = apply_patch(form, sources, patch)
    assert "diarrhea" not in [q.key for q in new.questions]
    assert "diarrhea" not in [s.question_key for s in new.side_effects]
    assert updated.root == {}  # 消した行と空にした欄の出どころは残らない


def test_clearing_a_referenced_question_key_needs_the_references_too() -> None:
    form = extra_form("folfiri_bv")
    key = FieldChange("questions.q-diarrhea.key", None)
    with pytest.raises(RegimenFormError) as exc:
        apply_patch(form, EMPTY, FormPatch(changes=(key,)))
    assert _codes(exc) == {
        ("side_effects.se-diarrhea.question_key", "unknown_question")
    }
    ref = FieldChange("side_effects.se-diarrhea.question_key", None)
    new, _sources = apply_patch(form, EMPTY, FormPatch(changes=(key, ref)))
    assert "diarrhea" not in [s.question_key for s in new.side_effects]


def test_deleting_the_temperature_question_with_references_is_still_rejected() -> None:
    form = extra_form("folfiri_bv")
    patch = FormPatch(
        deletes=("questions.q-fever",),
        changes=(FieldChange("side_effects.se-fever.question_key", None),),
    )
    with pytest.raises(RegimenFormError) as exc:
        apply_patch(form, EMPTY, patch)
    assert _codes(exc) == {("questions", "temperature_required")}

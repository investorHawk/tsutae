"""report.gate の入口の検査と、変換の入力（pipeline.inputs）との伏せ字の一致。

正規化すると空になる自由記載（ゼロ幅空白・BOM・ソフトハイフンだけ）は、変換の入力では
「自由記載なし」（None）になる。gate が同じ記録を '' と見ると entry_mismatch になり、
AI変換なし版も作れなくなる（仕上げのレビュー指摘6）。症例は全て合成。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tsutae.config import JST
from tsutae.pipeline import inputs as pipeline_inputs
from tsutae.pipeline.inputs import prepare_input
from tsutae.report import build_report_data
from tsutae.report.gate import check_inputs, mask_free_text
from tsutae.report.sample import SampleInputs, load_demo_inputs
from tsutae.schemas import ConversionResult, Entry

FORMAT_ONLY = ["​", "﻿", "­​", "⁠", " ​\n"]
SAMPLES = [
    *FORMAT_ONLY,
    None,
    "",
    "   ",
    "下痢が3回あった",
    "磯鷲さんに会った",  # 二次で外れる（架空の姓＋さん）
    "朝から\nだるい",
]


@pytest.fixture(scope="module")
def demo() -> SampleInputs:
    return load_demo_inputs()


@pytest.mark.parametrize("text", SAMPLES, ids=repr)
def test_gate_masking_is_the_pipeline_masking(text: str | None) -> None:
    assert mask_free_text(text) == pipeline_inputs.mask_free_text(text)


@pytest.mark.parametrize("text", FORMAT_ONLY, ids=repr)
def test_format_characters_only_is_no_free_text(text: str) -> None:
    assert mask_free_text(text) == (None, None)


def _zero_width_entry(demo: SampleInputs, text: str) -> Entry:
    when = datetime(2026, 11, 8, 22, 0, tzinfo=JST)  # C3 の最終日前（今コース）
    return Entry(
        id=901,
        patient_id=demo.patient_id,
        recorded_at=when,
        record_date=when.date(),
        kind="free_text",
        by_proxy=False,
        skill_version="regimen-folfox@1",
        free_text=text,
    )


@pytest.mark.parametrize("text", FORMAT_ONLY, ids=repr)
def test_prepared_input_with_format_only_text_passes_the_gate(
    demo: SampleInputs, text: str
) -> None:
    entries = [*demo.entries, _zero_width_entry(demo, text)]
    prepared = prepare_input(
        courses=demo.courses,
        entries=entries,
        regimen_skill=demo.regimen_skill,
        report_skill=demo.report_skill,
        visit_date=demo.visit_date,
    )
    no = next(n for n, eid in prepared.entry_ids.items() if eid == 901)
    assert no not in prepared.masked_texts
    check_inputs(
        patient_id=demo.patient_id,
        regimen_skill=demo.regimen_skill,
        report_skill=demo.report_skill,
        courses=demo.courses,
        entries=entries,
        visit_date=demo.visit_date,
        prepared=prepared,
        questions_by_version=demo.questions_by_version,
    )
    fallback = ConversionResult(
        timeline=None, picks=None, fallback=True, error_code="no_timeline"
    )
    data = build_report_data(
        **{
            **demo.build_kwargs(),
            "entries": entries,
            "prepared": prepared,
            "result": fallback,
        }
    )
    assert data.fallback is True


# ---------------------------------------------------------------------------
# 医師の伏せ字（D6）: prepare_input と gate が同じ規則で当てる
# ---------------------------------------------------------------------------

SUSPECT_ENTRY = 38  # demo_patient の「磯鷲さんに…」（二次で外れる記録）


def _doctor_mask(*spans: tuple[int, int], allowed=(), confirmed=False):
    from tsutae.schemas import DoctorMask, TextSpan

    return DoctorMask(
        spans=[TextSpan(start=s, end=e) for s, e in spans],
        confirmed_clear=confirmed,
        allowed=[TextSpan(start=s, end=e) for s, e in allowed],
    )


def _prepare_with(demo: SampleInputs, masks):
    return prepare_input(
        courses=demo.courses,
        entries=demo.entries,
        regimen_skill=demo.regimen_skill,
        report_skill=demo.report_skill,
        visit_date=demo.visit_date,
        doctor_masks=masks,
    )


def _fallback_report(demo: SampleInputs, prepared, masks):
    fallback = ConversionResult(
        timeline=None, picks=None, fallback=True, error_code="no_timeline"
    )
    return build_report_data(
        **{
            **demo.build_kwargs(),
            "prepared": prepared,
            "result": fallback,
            "doctor_masks": masks,
        }
    )


@pytest.mark.parametrize(
    "mask",
    [
        _doctor_mask((0, 2)),
        _doctor_mask(allowed=[(0, 4)], confirmed=True),
    ],
    ids=["masked", "confirmed"],
)
def test_gate_accepts_record_sent_with_doctor_mask(demo: SampleInputs, mask) -> None:
    masks = {SUSPECT_ENTRY: mask}
    prepared = _prepare_with(demo, masks)
    assert prepared.unprocessed == []
    data = _fallback_report(demo, prepared, masks)
    assert all(item.kind != "unprocessed" for item in data.attention)


def test_gate_rejects_doctor_masked_input_without_the_same_masks(
    demo: SampleInputs,
) -> None:
    from tsutae.report.errors import ReportBuildError

    masks = {SUSPECT_ENTRY: _doctor_mask((0, 2))}
    prepared = _prepare_with(demo, masks)
    with pytest.raises(ReportBuildError) as err:
        _fallback_report(demo, prepared, {})
    assert err.value.code == "entry_mismatch"


def test_gate_rejects_allowed_suspects_it_cannot_rebuild(demo: SampleInputs) -> None:
    from tsutae.report.errors import ReportBuildError

    masks = {SUSPECT_ENTRY: _doctor_mask((0, 2))}
    prepared = _prepare_with(demo, masks).model_copy(
        update={"allowed_suspects": ["磯鷲さん"]}
    )
    with pytest.raises(ReportBuildError) as err:
        _fallback_report(demo, prepared, masks)
    assert err.value.code == "entry_mismatch"


def test_gate_masking_uses_the_doctor_mask_like_the_pipeline() -> None:
    mask = _doctor_mask((0, 2))
    text = "磯鷲さんに会った"
    assert mask_free_text(text, mask) == pipeline_inputs.mask_free_text(text, mask)
    assert mask_free_text(text, mask)[1] is None


@pytest.mark.parametrize("drop", ["one", "all"])
def test_gate_rejects_entries_without_version(demo: SampleInputs, drop: str) -> None:
    from tsutae.report.errors import ReportBuildError

    versions = dict(demo.prepared.entry_versions)
    if drop == "all":
        versions = {}
    else:
        versions.pop(min(versions))
    prepared = demo.prepared.model_copy(update={"entry_versions": versions})
    kwargs = {**demo.build_kwargs(), "prepared": prepared}
    with pytest.raises(ReportBuildError) as exc:
        build_report_data(**kwargs)
    assert exc.value.code == "entry_mismatch"

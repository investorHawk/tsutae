"""医師の伏せ字を変換の入力に当てる（pipeline.inputs）。症例は全て合成。

- 順序: 生の原文に医師の区間を当てて `[伏せ字]` → 仮名ID・受付番号の照合 →
  check_text（正規化 → 一次 → 二次）→ 依頼文の形での二次
- 伏せた後に疑いが無ければ送る（時系列・引用に入る）。疑いが残れば未処理のまま
- 確かめて送る（confirmed_clear）は、保存の時点で残っていた区間の語だけを許す
- 医師の伏せ字が無い記録・空の対応表では今と同じ
"""

from __future__ import annotations

import pytest
from pipeline_fakes import load_case, regimen_skill, report_skill

from tsutae.dataset import to_courses, to_entries
from tsutae.masking import GENERIC_MASK, RULE_LONG_DIGITS, check_text
from tsutae.pipeline.inputs import (
    REASON_DOCTOR_MASK_INVALID,
    REASON_KNOWN_IDENTIFIER,
    mask_entry_text,
    mask_free_text,
    prepare_input,
)
from tsutae.pipeline.logs import MemoryLogger
from tsutae.schemas import DoctorMask, TextSpan

RAW = "磯鷲さんにもらった漢方をのんでみた。おなかがあったかい感じ"
SUSPECT_ENTRY = 38  # demo_patient の未処理の記録（原文は RAW）


def _mask(*spans: tuple[int, int], confirmed: bool = False, allowed=()) -> DoctorMask:
    return DoctorMask(
        spans=[TextSpan(start=s, end=e) for s, e in spans],
        confirmed_clear=confirmed,
        allowed=[TextSpan(start=s, end=e) for s, e in allowed],
    )


def _prepare(doctor_masks=None, exclude_literals=(), logger=None):
    patient, _labels = load_case("demo_patient")
    return prepare_input(
        courses=to_courses(patient),
        entries=to_entries(patient),
        regimen_skill=regimen_skill(patient.regimen),
        report_skill=report_skill(),
        visit_date=patient.visit_date,
        exclude_literals=exclude_literals,
        doctor_masks=doctor_masks,
        logger=logger,
    )


def _sent_text(prepared, entry_id: int) -> str | None:
    for no, eid in prepared.entry_ids.items():
        if eid == entry_id:
            return prepared.masked_texts.get(no)
    return None


# --- mask_entry_text --------------------------------------------------------


def test_without_doctor_mask_it_is_the_same_as_mask_free_text() -> None:
    for text in (RAW, "下痢が3回", "", "  ", None, "連絡は x@y まで"):
        outcome = mask_entry_text(text)
        assert (outcome.masked, outcome.reason) == mask_free_text(text)
        assert outcome.allowed == ()


def test_doctor_spans_are_applied_before_primary_masking() -> None:
    outcome = mask_entry_text(RAW, _mask((0, 2)))
    assert outcome.reason is None
    assert outcome.masked == GENERIC_MASK + RAW[2:]
    assert mask_free_text(RAW, _mask((0, 2))) == (outcome.masked, None)


def test_remaining_suspect_keeps_the_record_unprocessed() -> None:
    text = "番号は1234567と磯鷲さん"
    outcome = mask_entry_text(text, _mask((11, 13)))
    assert outcome.masked is None
    assert outcome.reason == RULE_LONG_DIGITS


def test_invalid_spans_keep_the_record_unprocessed() -> None:
    outcome = mask_entry_text(RAW, _mask((0, 999)))
    assert (outcome.masked, outcome.reason) == (None, REASON_DOCTOR_MASK_INVALID)


def test_confirmed_clear_allows_exactly_the_saved_suspect() -> None:
    masked = check_text(RAW).masked
    assert masked == RAW
    outcome = mask_entry_text(RAW, _mask(confirmed=True, allowed=[(0, 4)]))
    assert outcome.reason is None
    assert outcome.masked == RAW
    assert outcome.allowed == ("磯鷲さん",)


def test_confirmed_clear_does_not_allow_other_suspects() -> None:
    text = "磯鷲さんと1234567"
    outcome = mask_entry_text(text, _mask(confirmed=True, allowed=[(0, 4)]))
    assert outcome.reason == RULE_LONG_DIGITS


def test_allowed_without_confirmed_clear_is_ignored() -> None:
    outcome = mask_entry_text(RAW, _mask(confirmed=False, allowed=[(0, 4)]))
    assert outcome.masked is None
    assert outcome.allowed == ()


def test_allowed_outside_the_masked_text_is_invalid() -> None:
    outcome = mask_entry_text(RAW, _mask(confirmed=True, allowed=[(0, 999)]))
    assert outcome.reason == REASON_DOCTOR_MASK_INVALID


# --- prepare_input ----------------------------------------------------------


def test_prepare_without_doctor_masks_is_unchanged() -> None:
    assert _prepare() == _prepare(doctor_masks={})
    prepared = _prepare()
    assert [u.entry_id for u in prepared.unprocessed] == [SUSPECT_ENTRY]
    assert prepared.allowed_suspects == []


def test_prepare_sends_record_masked_by_doctor() -> None:
    before = _prepare()
    prepared = _prepare({SUSPECT_ENTRY: _mask((0, 2))})
    assert prepared.unprocessed == []
    assert len(prepared.entry_ids) == len(before.entry_ids) + 1
    assert _sent_text(prepared, SUSPECT_ENTRY) == GENERIC_MASK + RAW[2:]
    assert prepared.allowed_suspects == []
    # 依頼文に入る記録にも伏せた文が載る
    no = next(n for n, e in prepared.entry_ids.items() if e == SUSPECT_ENTRY)
    sent = next(me for me in prepared.input.entries if me.entry_no == no)
    assert sent.masked_free_text == GENERIC_MASK + RAW[2:]


def test_prepare_confirmed_record_passes_allowed_to_h1() -> None:
    prepared = _prepare({SUSPECT_ENTRY: _mask(confirmed=True, allowed=[(0, 4)])})
    assert prepared.unprocessed == []
    assert _sent_text(prepared, SUSPECT_ENTRY) == RAW
    assert prepared.allowed_suspects == ["磯鷲さん"]


def test_known_identifier_is_checked_after_doctor_spans() -> None:
    patient, _labels = load_case("demo_patient")
    entries = to_entries(patient)
    sent_ids = set(_prepare().entry_ids.values())
    index = next(i for i, e in enumerate(entries) if e.id in sent_ids)
    target = entries[index]
    raw = "受付はA-023でした"
    entries[index] = target.model_copy(update={"free_text": raw})
    kwargs = dict(
        courses=to_courses(patient),
        regimen_skill=regimen_skill(patient.regimen),
        report_skill=report_skill(),
        visit_date=patient.visit_date,
        exclude_literals=("A-023",),
    )
    plain = prepare_input(entries=entries, **kwargs)
    assert any(
        u.entry_id == target.id and u.reason == REASON_KNOWN_IDENTIFIER
        for u in plain.unprocessed
    )
    # 医師が受付番号を伏せれば送れる。確かめても受付番号そのものは許さない
    masked = prepare_input(
        entries=entries, doctor_masks={target.id: _mask((3, 8))}, **kwargs
    )
    assert all(u.entry_id != target.id for u in masked.unprocessed)
    confirmed = prepare_input(
        entries=entries,
        doctor_masks={target.id: _mask(confirmed=True, allowed=[(3, 8)])},
        **kwargs,
    )
    assert any(
        u.entry_id == target.id and u.reason == REASON_KNOWN_IDENTIFIER
        for u in confirmed.unprocessed
    )


def test_prepare_does_not_change_raw_entries() -> None:
    patient, _labels = load_case("demo_patient")
    entries = to_entries(patient)
    snapshot = [e.model_copy() for e in entries]
    prepare_input(
        courses=to_courses(patient),
        entries=entries,
        regimen_skill=regimen_skill(patient.regimen),
        report_skill=report_skill(),
        visit_date=patient.visit_date,
        doctor_masks={SUSPECT_ENTRY: _mask((0, 2))},
    )
    assert entries == snapshot


def test_prepare_logs_doctor_masks_without_text() -> None:
    logger = MemoryLogger()
    _prepare({SUSPECT_ENTRY: _mask(confirmed=True, allowed=[(0, 4)])}, logger=logger)
    assert logger.find("doctor_masks_applied") == [
        {"event": "doctor_masks_applied", "decision": "sent:1"}
    ]
    assert logger.find("doctor_confirmed_sent") == [
        {"event": "doctor_confirmed_sent", "decision": "sent:1"}
    ]


def test_prepare_without_doctor_masks_logs_nothing_new() -> None:
    logger = MemoryLogger()
    _prepare(logger=logger)
    assert [r["event"] for r in logger.records] == ["input_prepared"]


@pytest.mark.parametrize("bad", [{"x": 1}, {SUSPECT_ENTRY: "spans"}])
def test_prepare_rejects_bad_doctor_masks(bad: object) -> None:
    with pytest.raises(TypeError):
        _prepare(bad)

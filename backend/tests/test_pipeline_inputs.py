"""tsutae.pipeline.inputs.prepare_input（今コースの選別・番号・伏せ字・未処理）。"""

from __future__ import annotations

import json
import random
from datetime import date

import pytest
from pipeline_fakes import (
    CASE_NAMES,
    course_last_days,
    load_case,
    prepare_case,
    regimen_skill,
    report_skill,
)

from tsutae.course import build_schedule
from tsutae.dataset import to_courses, to_entries
from tsutae.masking import (
    RULE_BEFORE_FACILITY,
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    Detection,
    check_text,
    detect_identifiers,
)
from tsutae.pipeline import inputs as inputs_module
from tsutae.pipeline.inputs import (
    REASON_KNOWN_IDENTIFIER,
    PrepareInputError,
    prepare_input,
)
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.prompt import build_prompt
from tsutae.schemas import Course, Entry, UnprocessedEntry

C3_DAY1 = date(2026, 10, 27)
C3_LAST = date(2026, 11, 9)
UNPROCESSED_SEQ = 38  # 辞書にない架空の姓＋さん（二次検出に掛かる）


def _demo():
    patient, _ = load_case("demo_patient")
    return patient, to_courses(patient), to_entries(patient)


def _prepare(courses, entries, visit_date, **kwargs):
    return prepare_input(
        courses=courses,
        entries=entries,
        regimen_skill=regimen_skill(),
        report_skill=report_skill(),
        visit_date=visit_date,
        **kwargs,
    )


def test_demo_c3_selects_current_course_records_only() -> None:
    prepared = prepare_case("demo_patient")
    assert prepared.input.schedule.course_no == 3
    dates = [e.record_date for e in prepared.input.entries]
    assert dates and min(dates) == C3_DAY1 and max(dates) == date(2026, 11, 8)
    sent_ids = sorted(prepared.entry_ids.values())
    assert sent_ids == [s for s in range(27, 41) if s != UNPROCESSED_SEQ]


def test_entry_no_is_consecutive_in_recorded_order() -> None:
    _, courses, entries = _demo()
    shuffled = entries[:]
    random.Random(0).shuffle(shuffled)
    before = list(shuffled)
    prepared = _prepare(courses, shuffled, C3_LAST)
    assert shuffled == before  # 引数を書き換えない
    nos = [e.entry_no for e in prepared.input.entries]
    assert nos == list(range(1, len(nos) + 1))
    by_id = {e.id: e for e in entries}
    recorded = [by_id[prepared.entry_ids[n]].recorded_at for n in nos]
    assert recorded == sorted(recorded)


def test_flagged_entry_is_removed_and_reported_by_rule_name() -> None:
    prepared = prepare_case("demo_patient")
    assert prepared.unprocessed == [
        UnprocessedEntry(entry_id=UNPROCESSED_SEQ, reason=RULE_UNKNOWN_BEFORE_HONORIFIC)
    ]
    assert UNPROCESSED_SEQ not in prepared.entry_ids.values()
    dumped = prepared.input.model_dump_json()
    assert "磯鷲" not in dumped


def test_too_sick_entries_are_kept_without_answers() -> None:
    prepared = prepare_case("demo_patient")
    sick = [e for e in prepared.input.entries if e.too_sick]
    assert [e.day for e in sick] == [3, 4, 5]
    assert all(not e.answers and e.masked_free_text is None for e in sick)
    assert all(e.entry_no not in prepared.masked_texts for e in sick)


def test_free_text_is_masked_and_listed_by_entry_no() -> None:
    prepared = prepare_case("demo_patient")
    texts = {e.entry_no: e.masked_free_text for e in prepared.input.entries}
    assert prepared.masked_texts == {n: t for n, t in texts.items() if t}
    last = prepared.input.entries[-1]
    assert prepared.entry_ids[last.entry_no] == 40
    assert last.masked_free_text is not None
    assert "○○先生" in last.masked_free_text and "佐藤" not in last.masked_free_text


def test_day_numbers_answers_and_proxy_are_carried() -> None:
    _, _, entries = _demo()
    by_id = {e.id: e for e in entries}
    prepared = prepare_case("demo_patient")
    for masked in prepared.input.entries:
        src = by_id[prepared.entry_ids[masked.entry_no]]
        assert masked.record_date == src.record_date
        assert masked.day == (src.record_date - C3_DAY1).days + 1
        assert masked.by_proxy == src.by_proxy
        assert masked.answers == src.answers
    assert prepared.input.entries[0].day == 1
    assert prepared.input.entries[-1].day == 13  # 最後の記録は 11/08


def test_visit_before_last_day_cuts_records_after_visit() -> None:
    prepared = prepare_case("demo_patient", visit_date=date(2026, 11, 3))
    dates = [e.record_date for e in prepared.input.entries]
    assert max(dates) == date(2026, 11, 3)
    assert prepared.unprocessed == []  # 11/05 の記録は範囲外


def _on_day(entry: Entry, new_id: int, day: int, **over: object) -> Entry:
    return entry.model_copy(
        update={
            "id": new_id,
            "recorded_at": entry.recorded_at.replace(day=day),
            "record_date": date(2026, 11, day),
            **over,
        }
    )


def test_records_after_last_day_are_not_sent() -> None:
    # 次コース未登録で受診が遅れた場合も Day1〜min(最終日, visit_date) だけ（§7）
    _, courses, entries = _demo()
    late = _on_day(entries[-1], 999, 11)
    prepared = _prepare(courses, [*entries, late], date(2026, 11, 12))
    assert 999 not in prepared.entry_ids.values()


def test_records_out_of_range_are_dropped_silently() -> None:
    # 範囲外（最終日より後・受診日より後）は黙って外す。unprocessed は「伏せ字漏れの疑い・
    # 識別子を含む」の意味だけ（§7 W2b）。件数はログに残す
    _, courses, entries = _demo()
    last = entries[-1]
    on_last_day = _on_day(last, 901, 9, free_text="口内炎がいたい")
    late_text = _on_day(last, 902, 11, free_text="きのうから口内炎が痛い")
    late_answers = _on_day(last, 903, 10, kind="answers", free_text=None)
    after_visit = _on_day(last, 904, 13, free_text="下痢")
    logger = MemoryLogger()
    prepared = _prepare(
        courses,
        [*entries, on_last_day, late_text, late_answers, after_visit],
        date(2026, 11, 12),
        logger=logger,
    )
    assert 901 in prepared.entry_ids.values()  # 最終日は送る
    sent = set(prepared.entry_ids.values())
    assert not sent & {902, 903, 904}
    assert prepared.unprocessed == [
        UnprocessedEntry(entry_id=UNPROCESSED_SEQ, reason=RULE_UNKNOWN_BEFORE_HONORIFIC)
    ]
    in_range = len(prepared.entry_ids) + len(prepared.unprocessed)
    out_of_range = len(entries) + 4 - in_range
    assert out_of_range >= 3
    assert logger.records == [
        {"event": "input_prepared", "decision": f"out_of_range_count:{out_of_range}"}
    ]


def test_out_of_range_count_counts_earlier_courses_too() -> None:
    _, courses, entries = _demo()
    logger = MemoryLogger()
    prepared = _prepare(courses, entries, C3_LAST, logger=logger)
    earlier = sum(1 for e in entries if e.record_date < C3_DAY1)
    assert earlier > 0
    assert len(prepared.entry_ids) + len(prepared.unprocessed) == len(entries) - earlier
    assert logger.find("input_prepared")[0]["decision"] == (
        f"out_of_range_count:{earlier}"
    )


def test_logger_is_optional_and_does_not_change_the_result() -> None:
    # logger は省略できる（純関数のまま使える）。渡しても入力は同じ
    _, courses, entries = _demo()
    logger = MemoryLogger()
    assert _prepare(courses, entries, C3_LAST, logger=logger) == _prepare(
        courses, entries, C3_LAST
    )
    assert logger.names() == ["input_prepared"]


# --- 改行・制御文字（正規化は masking.check_text に任せる。§7 W2b）-----------

LINE_BREAK_TEXTS = [
    "朝から下痢。\nセンターで点滴した",
    "下痢が続いた。\n病院に電話した",
    "下痢が続いた。\r\nクリニックに電話した",
    "だるい\n医院へ",
]


def _with_last_text(text: str, **kwargs):
    _, courses, entries = _demo()
    changed = entries[-1].model_copy(update={"free_text": text})
    return _prepare(courses, [*entries[:-1], changed], C3_LAST, **kwargs), changed.id


def _no_of(prepared, entry_id: int) -> int:
    return next(n for n, i in prepared.entry_ids.items() if i == entry_id)


@pytest.mark.parametrize("text", LINE_BREAK_TEXTS)
def test_line_breaks_do_not_trip_h1_on_the_whole_prompt(text: str) -> None:
    prepared, entry_id = _with_last_text(text)
    assert entry_id in prepared.entry_ids.values()  # その記録も送る
    masked = prepared.masked_texts[_no_of(prepared, entry_id)]
    assert "\n" in masked and "\r" not in masked  # 改行は残す（CRLF は \n）
    assert prepared.unprocessed == [
        UnprocessedEntry(entry_id=UNPROCESSED_SEQ, reason=RULE_UNKNOWN_BEFORE_HONORIFIC)
    ]
    assert detect_identifiers(build_prompt(prepared)) == []


@pytest.mark.parametrize(
    "text",
    ["下痢。\r\nだるい\nので\t休んだ", "  下痢\n", "熱が出た。\u2028だるい"],
)
def test_masked_text_is_exactly_what_check_text_returns(text: str) -> None:
    # pipeline は改行を空白にしない。masked_texts は check_text の masked そのもの
    prepared, entry_id = _with_last_text(text)
    no = _no_of(prepared, entry_id)
    assert prepared.masked_texts[no] == check_text(text).masked
    assert prepared.input.entries[no - 1].masked_free_text == check_text(text).masked


def test_crlf_and_tab_are_normalized_by_masking() -> None:
    prepared, entry_id = _with_last_text("下痢。\r\nだるい\nので\t休んだ")
    assert prepared.masked_texts[_no_of(prepared, entry_id)] == (
        "下痢。\nだるい\nので 休んだ"
    )


def test_name_split_by_line_break_is_still_flagged() -> None:
    prepared, entry_id = _with_last_text("担当者\nさんに聞いた")
    assert entry_id not in prepared.entry_ids.values()
    assert (
        UnprocessedEntry(entry_id=entry_id, reason=RULE_UNKNOWN_BEFORE_HONORIFIC)
        in prepared.unprocessed
    )


@pytest.mark.parametrize("text", ["   ", " \n\t ", "\x07\x07", "\u200b"])
def test_blank_text_is_no_free_text(text: str) -> None:
    prepared, entry_id = _with_last_text(text)
    no = _no_of(prepared, entry_id)
    assert no not in prepared.masked_texts
    assert prepared.input.entries[no - 1].masked_free_text is None


# --- Unicode の書式文字（Cf）を挟んだ識別子（masking.normalize_text が消す）-----

FORMAT_CHAR_TEXTS = [
    ("090\u200b1234\u200b5678に電話した", "5678"),
    ("山田\u200bさん", "山田"),
    ("山\u200b田\u200b花\u200b子さんと", "花"),
    ("東京\u200b病院に行った", "東京"),
    ("山田\u00adさん", "山田"),
    ("山田\ufeffさん", "山田"),
    ("山田\u2060さんと", "山田"),
]


@pytest.mark.parametrize(("text", "secret"), FORMAT_CHAR_TEXTS)
def test_format_characters_do_not_hide_identifiers(text: str, secret: str) -> None:
    prepared, entry_id = _with_last_text(text)
    prompt = build_prompt(prepared)
    assert secret not in prompt
    for ch in ("\u200b", "\u00ad", "\ufeff", "\u2060"):
        assert ch not in prompt
    assert detect_identifiers(prompt) == []
    if entry_id in prepared.entry_ids.values():
        masked = prepared.masked_texts[_no_of(prepared, entry_id)]
        assert "○○" in masked or "[伏せ字]" in masked or "[病院]" in masked


# --- 仮名ID・受付番号（exclude_literals と一次の [ID]）---------------------------

IDS = ("P-DEMO0001", "A-023")


@pytest.mark.parametrize(
    "text",
    [
        "受付はA-023だった",
        "P-DEMO0001 の画面で入力",
        "ｐ－ｄｅｍｏ０００１で登録",  # 全角・小文字（NFKC＋casefold）
        "Ａ－０２３番で待った",
        "a-023",
    ],
)
def test_text_with_known_identifier_is_not_sent(text: str) -> None:
    prepared, entry_id = _with_last_text(text, exclude_literals=IDS)
    assert entry_id not in prepared.entry_ids.values()
    assert prepared.unprocessed == [
        UnprocessedEntry(
            entry_id=UNPROCESSED_SEQ, reason=RULE_UNKNOWN_BEFORE_HONORIFIC
        ),
        UnprocessedEntry(entry_id=entry_id, reason=REASON_KNOWN_IDENTIFIER),
    ]
    dumped = build_prompt(prepared).casefold()
    assert "023" not in dumped and "demo0001" not in dumped


# 改行・タブ・空白で分割しても既知の識別子として外す（一次・二次は分割形を拾わない）
SEPARATORS = ("\r\n", "\n", "\r", "\t", "\u2028", "\u2029", " ", "\u3000")
SPLIT_IDS = [
    *(f"P-{sep}DEMO0001" for sep in SEPARATORS),
    *(f"P{sep}-DEMO0001" for sep in SEPARATORS),
    *(f"P-DEMO{sep}0001" for sep in SEPARATORS),
    *(f"A-{sep}023" for sep in SEPARATORS),
    *(f"A{sep}-023" for sep in SEPARATORS),
    *(f"A-0{sep}23" for sep in SEPARATORS),
    "a -\t\n 0 2 3",
]


@pytest.mark.parametrize("split", SPLIT_IDS, ids=repr)
def test_known_identifier_split_by_whitespace_is_not_sent(split: str) -> None:
    prepared, entry_id = _with_last_text(f"受付は{split}だった", exclude_literals=IDS)
    assert entry_id not in prepared.entry_ids.values()
    assert UnprocessedEntry(entry_id=entry_id, reason=REASON_KNOWN_IDENTIFIER) in (
        prepared.unprocessed
    )
    squashed = "".join(build_prompt(prepared).casefold().split())
    for escape in ("\\n", "\\r", "\\t"):
        squashed = squashed.replace(escape, "")
    assert "a-023" not in squashed and "p-demo0001" not in squashed


def test_literal_with_whitespace_is_compared_without_it() -> None:
    prepared, entry_id = _with_last_text(
        "受付はA-023だった", exclude_literals=[" A - 023\n"]
    )
    assert UnprocessedEntry(entry_id=entry_id, reason=REASON_KNOWN_IDENTIFIER) in (
        prepared.unprocessed
    )


def test_known_identifier_takes_precedence_over_masking_rules() -> None:
    # 一次で [ID] に置き換わる形でも、既知の識別子なら記録ごと外す
    prepared, entry_id = _with_last_text(
        "P-DEMO0001 磯鷲さん", exclude_literals=["P-DEMO0001"]
    )
    assert UnprocessedEntry(entry_id=entry_id, reason=REASON_KNOWN_IDENTIFIER) in (
        prepared.unprocessed
    )


def test_empty_and_unrelated_literals_exclude_nothing() -> None:
    plain = prepare_case("demo_patient")
    _, courses, entries = _demo()
    prepared = _prepare(courses, entries, C3_LAST, exclude_literals=["", "Z-999"])
    assert prepared == plain


def test_known_identifier_check_looks_only_at_free_text() -> None:
    # 「3」を既知の識別子とみなすと、自由記載に 3 を含む今コースの記録だけが外れる
    _, courses, entries = _demo()
    prepared = _prepare(courses, entries, C3_LAST, exclude_literals=["3"])
    expected = {
        e.id
        for e in entries
        if C3_DAY1 <= e.record_date <= C3_LAST and e.free_text and "3" in e.free_text
    }
    excluded = {
        u.entry_id for u in prepared.unprocessed if u.reason == REASON_KNOWN_IDENTIFIER
    }
    assert expected and excluded == expected
    assert [e.day for e in prepared.input.entries if e.too_sick] == [3, 4, 5]


@pytest.mark.parametrize("bad", ["P-DEMO0001", [None], [1]])
def test_exclude_literals_must_be_a_sequence_of_strings(bad: object) -> None:
    _, courses, entries = _demo()
    with pytest.raises(TypeError):
        _prepare(courses, entries, C3_LAST, exclude_literals=bad)


def test_pseudonym_in_free_text_is_masked_even_without_literals() -> None:
    # 一次が仮名IDの形を [ID] に、二次が id_like で取り残しを拾う（masking §5 W2b）
    prepared, entry_id = _with_last_text("P-DEMO0001 で登録した")
    assert "DEMO0001" not in build_prompt(prepared)


def test_detection_in_the_json_form_removes_only_that_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 依頼文の JSON の形でだけ掛かる検出（二次の規則の変更に備える）もその記録だけ外す
    def fake_detect(text: str) -> list[Detection]:
        return [Detection(RULE_BEFORE_FACILITY, 0, 1)] if "しゃっくり" in text else []

    monkeypatch.setattr(inputs_module, "detect_identifiers", fake_detect)
    prepared = prepare_case("demo_patient")
    assert 28 not in prepared.entry_ids.values()
    assert UnprocessedEntry(entry_id=28, reason=RULE_BEFORE_FACILITY) in (
        prepared.unprocessed
    )
    assert len(prepared.input.entries) == 12


@pytest.mark.parametrize("name", CASE_NAMES)
def test_every_sent_text_passes_the_detector_in_json_form(name: str) -> None:
    for visit_date in course_last_days(name):
        prepared = prepare_case(name, visit_date)
        for no, text in prepared.masked_texts.items():
            dumped = json.dumps(text, ensure_ascii=False)
            assert detect_identifiers(dumped) == [], (name, visit_date, no)


def test_pipeline_input_fields_from_skills_and_schedule() -> None:
    patient, courses, _ = _demo()
    skill = regimen_skill()
    prepared = prepare_case("demo_patient")
    assert prepared.input.regimen == "FOLFOX"
    assert prepared.input.regimen_skill_version == "regimen-folfox@1"
    assert prepared.input.report_skill_version == "report-format-default@1"
    assert prepared.input.questions == skill.questions
    assert prepared.input.schedule == build_schedule(
        courses, 3, skill.cycle_days, skill.pump_removal_day
    )


def test_no_pseudonym_or_reception_number_in_input() -> None:
    patient, _ = load_case("demo_patient")
    dumped = json.dumps(
        prepare_case("demo_patient").input.model_dump(mode="json"), ensure_ascii=False
    )
    assert patient.patient_id not in dumped
    assert patient.reception_no not in dumped


def test_previous_course_visit_uses_that_course() -> None:
    prepared = prepare_case("demo_patient", visit_date=date(2026, 10, 20))
    assert prepared.input.schedule.course_no == 2
    dates = [e.record_date for e in prepared.input.entries]
    assert min(dates) >= date(2026, 10, 13) and max(dates) <= date(2026, 10, 20)


def test_no_current_course_raises() -> None:
    _, courses, entries = _demo()
    with pytest.raises(PrepareInputError) as exc:
        _prepare(courses, entries, date(2026, 9, 1))
    assert exc.value.code == "no_current_course"


def test_entries_of_another_patient_are_rejected() -> None:
    _, courses, entries = _demo()
    other = entries[-1].model_copy(update={"patient_id": "P-OTHER001"})
    with pytest.raises(PrepareInputError) as exc:
        _prepare(courses, [*entries, other], C3_LAST)
    assert exc.value.code == "patient_mismatch"


def test_courses_of_another_patient_are_rejected() -> None:
    _, courses, entries = _demo()
    foreign = [c.model_copy(update={"patient_id": "P-OTHER001"}) for c in courses]
    with pytest.raises(PrepareInputError) as exc:
        _prepare(foreign, entries, C3_LAST)
    assert exc.value.code == "patient_mismatch"


def test_empty_entries_give_empty_input() -> None:
    _, courses, _ = _demo()
    prepared = _prepare(courses, [], C3_LAST)
    assert prepared.input.entries == []
    assert prepared.entry_ids == {} and prepared.masked_texts == {}


def test_single_course_list_is_accepted() -> None:
    course = Course(patient_id="P-DEMO0001", course_no=1, infusion_date=C3_DAY1)
    _, _, entries = _demo()
    prepared = _prepare([course], entries, C3_LAST)
    assert prepared.input.schedule.course_no == 1
    assert prepared.input.schedule.previous_infusion_date is None

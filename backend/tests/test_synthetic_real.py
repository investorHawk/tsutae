"""data/synthetic の実データの検査（tsutae.synthetic の検査＋デモ・評価用の要件）。

デモの要件は受診するコース（C3）に絞って確かめる（受診時の変換は今コースしか見ない）。
実データの写しを書き換えた回帰テストで、要件の検査が働くことも確かめる。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tsutae import config, synthetic
from tsutae.schemas import EntryLabel, PatientLabels, SyntheticEntry, SyntheticPatient

Pair = tuple[SyntheticPatient, PatientLabels]

DEMO_PID = "P-DEMO0001"
DEMO_COURSES = {
    1: (date(2026, 9, 27), None),
    2: (date(2026, 10, 13), date(2026, 10, 11)),
    3: (date(2026, 10, 27), None),
}
RELATIVE_PHRASES = ("点滴の次の日から", "先週木曜まで", "ポンプを外した日")
# 引用に入ってはいけない識別子らしい文字列（敬称・施設・@・7桁以上の数字列）
QUOTE_IDENTIFIER = re.compile(
    r"さん|先生|くん|ちゃん|様|病院|医院|クリニック|センター|[@＠]"
    r"|[0-9０-９](?:[-－‐ ]?[0-9０-９]){6,}"
)


def _real_files() -> list[Path]:
    base = config.SYNTHETIC_DIR
    return [
        path
        for name in synthetic.DATASET_NAMES
        for path in (base / f"{name}.json", base / f"labels_{name}.json")
    ]


@pytest.fixture(scope="module")
def real_pairs() -> list[Pair]:
    missing = [p.name for p in _real_files() if not p.exists()]
    if missing:
        pytest.skip(f"data/synthetic が揃っていない: {missing}")
    return synthetic.all_patients()  # DATASET_NAMES の先頭が demo_patient


def _record_date(entry: SyntheticEntry) -> date:
    return config.to_jst_date(entry.recorded_at)


def _c3_dates(patient: SyntheticPatient) -> list[date]:
    """C3 の Day1〜受診日の前日（受診日 = Day14 なので Day1〜13）。"""
    start = DEMO_COURSES[3][0]
    return [start + timedelta(days=i) for i in range((patient.visit_date - start).days)]


def _c3_labels(patient: SyntheticPatient, labels: PatientLabels) -> list[EntryLabel]:
    dates = {e.seq: _record_date(e) for e in patient.entries}
    start, end = DEMO_COURSES[3][0], patient.visit_date
    return [lb for lb in labels.labels if start <= dates[lb.entry_seq] <= end]


# ---------------------------------------------------------------------------
# デモ
# ---------------------------------------------------------------------------


def _demo_header_problems(patient: SyntheticPatient) -> list[str]:
    problems = []
    expected = (DEMO_PID, "demo", date(2026, 11, 9), "A-023")
    actual = (
        patient.patient_id,
        patient.role,
        patient.visit_date,
        patient.reception_no,
    )
    if actual != expected:
        problems.append(f"デモの見出しが違う: {actual}")
    courses = {c.course_no: (c.infusion_date, c.planned_date) for c in patient.courses}
    for no, (infusion, planned) in DEMO_COURSES.items():
        got = courses.get(no)
        if got is None or got[0] != infusion or (planned and got[1] != planned):
            problems.append(f"C{no} の日程が違う: {got}")
    c2 = courses.get(2)
    if c2 and (c2[1] is None or (c2[0] - c2[1]).days != 2):
        problems.append("C2 の延期が2日でない")
    if synthetic.expected_course_day(patient.courses, patient.visit_date) != (3, 14):
        problems.append("受診日が C3 Day14 でない")
    return problems


def _demo_entry_problems(patient: SyntheticPatient) -> list[str]:
    problems = []
    by_date: dict[date, list[SyntheticEntry]] = {}
    for e in patient.entries:
        by_date.setdefault(_record_date(e), []).append(e)
    for no, (infusion, _) in DEMO_COURSES.items():
        for day in (3, 4, 5):
            d = infusion + timedelta(days=day - 1)
            if not any(e.too_sick for e in by_date.get(d, [])):
                problems.append(f"C{no} Day{day}（{d}）に too_sick が無い")
    c3_day8 = DEMO_COURSES[3][0] + timedelta(days=7)
    temps = [
        a.temperature
        for e in by_date.get(c3_day8, [])
        for a in e.answers
        if a.question_key == "fever" and a.value == "measured"
    ]
    if 37.9 not in temps:
        problems.append(f"C3 Day8（{c3_day8}）に 37.9℃ が無い: {temps}")
    c3 = _c3_dates(patient)
    proxy_days = [d for d in c3 if any(e.by_proxy for e in by_date.get(d, []))]
    if len(proxy_days) != 1:
        problems.append(f"C3 の代理入力の日が1日でない: {proxy_days}")
    if all(d in by_date for d in c3):
        problems.append("C3 の Day1〜13 に入力なしの日が無い")
    return problems


def _demo_label_problems(patient: SyntheticPatient, labels: PatientLabels) -> list[str]:
    problems = []
    dates = {e.seq: _record_date(e) for e in patient.entries}
    c3_day5 = DEMO_COURSES[3][0] + timedelta(days=4)
    has_c3_day5_diarrhea = any(
        dates.get(lb.entry_seq) == c3_day5
        and c.question_key == "diarrhea"
        and c.closed_answer == "none"
        for lb in labels.labels
        for c in lb.contradictions
    )
    if not has_c3_day5_diarrhea:
        problems.append(f"C3 Day5（{c3_day5}）の下痢の食い違いが無い")
    c3_labels = _c3_labels(patient, labels)
    recalled = [ev.source_quote for lb in c3_labels for ev in lb.events if ev.recalled]
    if len(recalled) != 1:
        problems.append(f"C3 の回想の出来事が1件でない: {recalled}")
    unprocessed = [lb.entry_seq for lb in labels.labels if lb.expect_unprocessed]
    if len(unprocessed) != 1:
        problems.append(f"expect_unprocessed が1件でない: {unprocessed}")
    if not any(lb.expect_unprocessed for lb in c3_labels):
        problems.append(f"expect_unprocessed の記録が C3 に無い: seq={unprocessed}")
    return problems


# ---------------------------------------------------------------------------
# 評価用・全体
# ---------------------------------------------------------------------------


def _eval_problems(pairs: list[Pair]) -> list[str]:
    problems = []
    demo_id = pairs[0][0].patient_id
    ids = [demo_id]
    for patient, _ in pairs[1:]:
        pid = patient.patient_id
        if patient.role != "eval":
            problems.append(f"{pid} の role が eval でない: {patient.role}")
        if len(patient.courses) != 2:
            problems.append(f"{pid} のコースが2件でない: {len(patient.courses)}")
        if pid in ids:
            problems.append(f"評価用の patient_id がデモか他の評価用と同じ: {pid}")
        ids.append(pid)
    return problems


def _phrase_problems(pairs: list[Pair]) -> list[str]:
    texts = [e.free_text or "" for p, _ in pairs for e in p.entries]
    problems = [
        f"相対時間「{phrase}」を含む自由記載が無い"
        for phrase in RELATIVE_PHRASES
        if not any(phrase in t for t in texts)
    ]
    for patient, labels in pairs:
        tags = {lb.entry_seq: lb.hard_case_tags for lb in labels.labels}
        problems += [
            f"{patient.patient_id} seq={e.seq}: 相対時間句があるのに relative_time が無い"
            for e in patient.entries
            if any(phrase in (e.free_text or "") for phrase in RELATIVE_PHRASES)
            and "relative_time" not in tags.get(e.seq, [])
        ]
    return problems


def _quote_identifier_problems(pairs: list[Pair]) -> list[str]:
    """引用は一次置換で消える識別子（敬称・施設・@・長い数字）を含まない。"""
    return [
        f"{labels.patient_id} seq={lb.entry_seq}: 引用「{quote}」に識別子らしい語"
        for _, labels in pairs
        for lb in labels.labels
        for quote in [
            *(ev.source_quote for ev in lb.events),
            *(c.free_text_quote for c in lb.contradictions),
        ]
        if QUOTE_IDENTIFIER.search(quote)
    ]


def _requirement_problems(pairs: list[Pair]) -> list[str]:
    """validate_dataset 以外の、実データだけに掛かる要件。"""
    demo, demo_labels = pairs[0]
    return [
        *_demo_header_problems(demo),
        *_demo_entry_problems(demo),
        *_demo_label_problems(demo, demo_labels),
        *_eval_problems(pairs),
        *_phrase_problems(pairs),
        *_quote_identifier_problems(pairs),
    ]


def test_real_dataset_is_valid(real_pairs: list[Pair]) -> None:
    problems = [
        *synthetic.validate_dataset(real_pairs),
        *_requirement_problems(real_pairs),
    ]
    assert problems == []


def test_real_hard_cases_are_plural(real_pairs: list[Pair]) -> None:
    counts = synthetic.hard_case_counts(lb for _, lb in real_pairs)
    assert min(counts.values()) >= synthetic.MIN_HARD_CASES


# ---------------------------------------------------------------------------
# 回帰: 実データの写しを書き換えると、要件の検査が問題を返す
# ---------------------------------------------------------------------------

Mutation = Callable[[list[Pair]], list[Pair]]


def _with_entry(pairs: list[Pair], idx: int, seq: int, **changes: Any) -> list[Pair]:
    patient, labels = pairs[idx]
    entries = [
        e.model_copy(update=changes) if e.seq == seq else e for e in patient.entries
    ]
    out = list(pairs)
    out[idx] = (patient.model_copy(update={"entries": entries}), labels)
    return out


def _with_label(pairs: list[Pair], idx: int, seq: int, **changes: Any) -> list[Pair]:
    patient, labels = pairs[idx]
    items = [
        lb.model_copy(update=changes) if lb.entry_seq == seq else lb
        for lb in labels.labels
    ]
    out = list(pairs)
    out[idx] = (patient, labels.model_copy(update={"labels": items}))
    return out


def _drop_c3_proxy(pairs: list[Pair]) -> list[Pair]:  # (A)
    return _with_entry(pairs, 0, 33, by_proxy=False)


def _c3_recall_to_record_date(pairs: list[Pair]) -> list[Pair]:  # (B)
    label = next(lb for lb in pairs[0][1].labels if lb.entry_seq == 35)
    events = [
        ev.model_copy(update={"date": date(2026, 11, 2), "day": 7, "recalled": False})
        for ev in label.events
    ]
    return _with_label(pairs, 0, 35, events=events)


def _move_unprocessed_to_c1(pairs: list[Pair]) -> list[Pair]:  # (C)
    moved = _with_label(pairs, 0, 38, expect_unprocessed=False)
    return _with_label(moved, 0, 2, expect_unprocessed=True)


def _fill_c3_no_input_days(pairs: list[Pair]) -> list[Pair]:  # (D)
    patient, labels = pairs[0]
    extra = [
        SyntheticEntry(
            seq=len(patient.entries) + i,
            recorded_at=config.jst_datetime(d, 20),
            answers=[{"question_key": "diarrhea", "value": "none"}],
        )
        for i, d in enumerate((date(2026, 11, 4), date(2026, 11, 6)), 1)
    ]
    filled = patient.model_copy(update={"entries": [*patient.entries, *extra]})
    return [(filled, labels), *pairs[1:]]


def _eval_as_demo(pairs: list[Pair]) -> list[Pair]:  # (E)
    patient, labels = pairs[1]
    return [pairs[0], (patient.model_copy(update={"role": "demo"}), labels), pairs[2]]


def _eval_one_course(pairs: list[Pair]) -> list[Pair]:
    patient, labels = pairs[2]
    one = patient.model_copy(update={"courses": patient.courses[:1]})
    return [*pairs[:2], (one, labels)]


def _eval_same_id_as_demo(pairs: list[Pair]) -> list[Pair]:
    patient, labels = pairs[1]
    same = patient.model_copy(update={"patient_id": DEMO_PID})
    return [pairs[0], (same, labels), pairs[2]]


def _drop_relative_tag(pairs: list[Pair]) -> list[Pair]:
    return _with_label(pairs, 0, 13, hard_case_tags=[])  # 「先週木曜まで」


def _identifier_in_quote(pairs: list[Pair]) -> list[Pair]:
    label = next(lb for lb in pairs[0][1].labels if lb.entry_seq == 25)
    events = [
        ev.model_copy(update={"source_quote": "となりの鈴木さん"})
        for ev in label.events
    ]
    return _with_label(pairs, 0, 25, events=events)


@pytest.mark.parametrize(
    ("mutate", "keyword"),
    [
        (_drop_c3_proxy, "C3 の代理入力"),
        (_c3_recall_to_record_date, "C3 の回想"),
        (_move_unprocessed_to_c1, "の記録が C3 に無い"),
        (_fill_c3_no_input_days, "入力なしの日が無い"),
        (_eval_as_demo, "role が eval でない"),
        (_eval_one_course, "コースが2件でない"),
        (_eval_same_id_as_demo, "patient_id がデモ"),
        (_drop_relative_tag, "relative_time が無い"),
        (_identifier_in_quote, "識別子らしい語"),
    ],
)
def test_requirement_check_catches(
    real_pairs: list[Pair], mutate: Mutation, keyword: str
) -> None:
    assert _requirement_problems(real_pairs) == []
    problems = _requirement_problems(mutate(real_pairs))
    assert any(keyword in p for p in problems), problems


# ---------------------------------------------------------------------------
# 伏せ字（tsutae.masking）との整合
# ---------------------------------------------------------------------------


def test_real_quotes_are_in_masked_text(real_pairs: list[Pair]) -> None:
    masking = pytest.importorskip("tsutae.masking")
    issues = synthetic.validate_dataset(
        real_pairs, mask=lambda text: masking.mask_text(text).masked
    )
    assert issues == []


def test_real_secondary_detection_matches_expect_unprocessed(
    real_pairs: list[Pair],
) -> None:
    masking = pytest.importorskip("tsutae.masking")
    mismatches = []
    for patient, labels in real_pairs:
        expected = {lb.entry_seq: lb.expect_unprocessed for lb in labels.labels}
        for e in patient.entries:
            if not e.free_text:
                continue
            masked = masking.mask_text(e.free_text).masked
            flagged = bool(masking.detect_identifiers(masked))
            if flagged != expected[e.seq]:
                mismatches.append((patient.patient_id, e.seq, flagged))
    assert mismatches == []

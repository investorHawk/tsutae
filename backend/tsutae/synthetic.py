"""合成データ（data/synthetic/*.json）と正解ラベルの読み込み・検査。

- 患者は `SyntheticPatient`、ラベルは `PatientLabels`（schemas.py）
- `validate_dataset` は問題を `"[コード] 患者ID seq=番号: 説明"` の文字列で返す。空なら OK
- Day の計算は tsutae.course に依存しない（Day1 = 実投与日、次コース実投与日の前日まで。
  最終コースは Day15, 16… と数え続ける）
- 引用（source_quote / free_text_quote）は、`mask` を渡せば一次置換後の文
  （`mask(自由記載)`）に、渡さなければ元の自由記載に部分一致するかで検査する
- 回想（recalled）= 出来事の暦日が記録日より前（相対時間で戻した場合も含む）
- 食い違いは、同じ記録日のクローズ回答と、回想でない出来事の status を
  question_key ごとに比べて決まる（`_conflicting_statuses`）
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any, get_args

from pydantic import ValidationError

from tsutae import config
from tsutae.config import JST, to_jst_date
from tsutae.schemas import (
    AnswerType,
    AnswerValue,
    ClosedAnswer,
    EntryCreate,
    EntryLabel,
    FeverValue,
    HardCaseTag,
    LabelContradiction,
    LabelEvent,
    PatientLabels,
    SyntheticCourse,
    SyntheticEntry,
    SyntheticPatient,
    ThreeLevel,
)

DATASET_NAMES: tuple[str, ...] = ("demo_patient", "eval_patient_a", "eval_patient_b")
EXPECTED_SKILL_VERSION = "regimen-folfox@1"
# regimen-folfox@1 の質問集（合成データの記録は全てこの版。SKILL.md との一致はテスト）
FOLFOX_ANSWER_TYPES: Mapping[str, AnswerType] = MappingProxyType(
    {
        "numbness": "three_level",
        "diarrhea": "three_level",
        "stomatitis": "three_level",
        "nausea_appetite": "three_level",
        "fever": "temperature",
    }
)
VALUES_BY_ANSWER_TYPE: Mapping[AnswerType, frozenset[str]] = MappingProxyType(
    {
        "three_level": frozenset(get_args(ThreeLevel)),
        "temperature": frozenset(get_args(FeverValue)),
    }
)
HARD_CASE_TAGS: tuple[str, ...] = get_args(HardCaseTag)
MIN_HARD_CASES = 2

PatientPair = tuple[SyntheticPatient, PatientLabels]
AnswersByDate = dict[date, list[ClosedAnswer]]
LabelledEntry = tuple[EntryLabel, SyntheticEntry]
Mask = Callable[[str], str]
Found = list[tuple[str, str]]  # (コード, 説明)


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------


def load_patient(path: Path) -> SyntheticPatient:
    """患者ファイルを読む。スキーマ違反は pydantic の ValidationError（ValueError）。"""
    return SyntheticPatient.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_labels(path: Path) -> PatientLabels:
    return PatientLabels.model_validate_json(Path(path).read_text(encoding="utf-8"))


def all_patients(directory: Path | None = None) -> list[PatientPair]:
    """demo_patient / eval_patient_a / eval_patient_b とそのラベルを読む。"""
    base = Path(directory) if directory is not None else config.SYNTHETIC_DIR
    return [
        (load_patient(base / f"{name}.json"), load_labels(base / f"labels_{name}.json"))
        for name in DATASET_NAMES
    ]


def load_terms(path: Path | None = None) -> list[dict[str, Any]]:
    """ctcae_terms.json の terms を返す。形が壊れていれば ValueError。"""
    target = (
        Path(path)
        if path is not None
        else config.PACKAGE_ROOT / "data" / "ctcae_terms.json"
    )
    raw = json.loads(target.read_text(encoding="utf-8"))
    terms = raw.get("terms") if isinstance(raw, dict) else None
    if not isinstance(terms, list):
        raise ValueError(f"{target.name}: terms が配列でない")
    for i, item in enumerate(terms):
        if not isinstance(item, dict) or not isinstance(item.get("term"), str):
            raise ValueError(f"{target.name}: terms[{i}] に term（文字列）が無い")
    return [dict(item) for item in terms]


def term_question_keys(terms: Iterable[Mapping[str, Any]]) -> dict[str, str | None]:
    """用語 → 対応するクローズ質問の key（無ければ None）。型が違えば ValueError。"""
    result: dict[str, str | None] = {}
    for i, item in enumerate(terms):
        term, key = item.get("term"), item.get("question_key")
        if not isinstance(term, str) or not (key is None or isinstance(key, str)):
            raise ValueError(f"terms[{i}] の term / question_key の型が違う")
        result[term] = key
    return result


def hard_case_counts(labels_list: Iterable[PatientLabels]) -> dict[str, int]:
    """難ケース4種それぞれのラベル件数（0 件のタグも含める）。"""
    counts = dict.fromkeys(HARD_CASE_TAGS, 0)
    for patient_labels in labels_list:
        for label in patient_labels.labels:
            for tag in set(label.hard_case_tags):
                counts[tag] += 1
    return counts


def expected_course_day(
    courses: Sequence[SyntheticCourse], d: date
) -> tuple[int, int] | None:
    """d が属するコースの (course_no, Day)。最初の実投与日より前なら None。"""
    started = [c for c in courses if c.infusion_date <= d]
    if not started:
        return None
    current = max(started, key=lambda c: c.infusion_date)
    return current.course_no, (d - current.infusion_date).days + 1


# ---------------------------------------------------------------------------
# 検査（全体・患者）
# ---------------------------------------------------------------------------


def validate_dataset(
    patients_and_labels: Iterable[PatientPair] | None = None,
    terms: Iterable[Mapping[str, Any]] | None = None,
    mask: Mask | None = None,
) -> list[str]:
    """データ一式の問題を列挙する。引数なしなら data/synthetic の3人を検査する。

    terms は `load_terms()` の形（既定は ctcae_terms.json）。mask（一次置換の関数）を
    渡すと、引用を一次置換後の自由記載に対して検査する。
    """
    pairs = (
        list(patients_and_labels) if patients_and_labels is not None else all_patients()
    )
    term_keys = term_question_keys(terms if terms is not None else load_terms())
    issues: list[str] = []
    for patient, labels in pairs:
        issues.extend(_check_patient(patient, labels, term_keys, mask))
    issues.extend(_check_hard_cases([labels for _, labels in pairs]))
    return issues


def _issue(code: str, pid: str, seq: int | None, detail: str) -> str:
    where = pid if seq is None else f"{pid} seq={seq}"
    return f"[{code}] {where}: {detail}"


def _check_patient(
    patient: SyntheticPatient,
    labels: PatientLabels,
    term_keys: Mapping[str, str | None],
    mask: Mask | None,
) -> list[str]:
    pid = patient.patient_id
    issues: list[str] = []
    if labels.patient_id != pid:
        issues.append(
            _issue("patient_id_mismatch", pid, None, f"ラベルは {labels.patient_id}")
        )
    issues.extend(_check_entries(patient))
    issues.extend(_check_entry_sequence(patient))
    issues.extend(_check_label_coverage(patient, labels))
    entries = {e.seq: e for e in patient.entries}
    labelled: list[LabelledEntry] = [
        (label, entries[label.entry_seq])
        for label in labels.labels
        if label.entry_seq in entries and entries[label.entry_seq].free_text
    ]
    answers = _answers_by_date(patient.entries)
    for label, entry in labelled:
        text = entry.free_text or ""
        text = mask(text) if mask is not None else text
        found = _check_label(label, entry, text, patient.courses, answers, term_keys)
        issues.extend(_issue(code, pid, entry.seq, detail) for code, detail in found)
    issues.extend(_check_required_contradictions(pid, labelled, answers))
    return issues


# ---------------------------------------------------------------------------
# 記録（EntryCreate と同じ不変条件・質問集・期間・seq の順）
# ---------------------------------------------------------------------------


def _check_entries(patient: SyntheticPatient) -> list[str]:
    pid = patient.patient_id
    span = (
        (min(c.infusion_date for c in patient.courses), patient.visit_date)
        if patient.courses
        else None
    )
    issues: list[str] = []
    for e in patient.entries:
        found = [
            *_check_entry_meta(e),
            *_check_entry_content(e),
            *_check_entry_range(e, span),
        ]
        issues.extend(_issue(code, pid, e.seq, detail) for code, detail in found)
    return issues


def _check_entry_meta(e: SyntheticEntry) -> Found:
    found: Found = []
    if e.recorded_at.tzinfo is None or e.recorded_at.utcoffset() is None:
        found.append(("naive_recorded_at", "recorded_at に時差が無い"))
    if e.skill_version != EXPECTED_SKILL_VERSION:
        detail = f"{e.skill_version}（期待 {EXPECTED_SKILL_VERSION}）"
        found.append(("skill_version_mismatch", detail))
    return found


def _check_entry_content(e: SyntheticEntry) -> Found:
    found: Found = []
    try:
        EntryCreate(
            too_sick=e.too_sick,
            by_proxy=e.by_proxy,
            answers=list(e.answers),
            free_text=e.free_text,
        )
    except ValidationError as exc:
        errors = exc.errors()
        found.append(("entry_invalid", errors[0]["msg"] if errors else str(exc)))
    for a in e.answers:
        answer_type = FOLFOX_ANSWER_TYPES.get(a.question_key)
        if answer_type is None:
            detail = f"回答の {a.question_key} は regimen-folfox の質問に無い"
            found.append(("unknown_question_key", detail))
        elif a.value not in VALUES_BY_ANSWER_TYPE[answer_type]:
            detail = f"{a.question_key}={a.value}（{answer_type} の値でない）"
            found.append(("answer_type_mismatch", detail))
    return found


def _check_entry_range(e: SyntheticEntry, span: tuple[date, date] | None) -> Found:
    d = to_jst_date(e.recorded_at)
    if span is None:
        return [("entry_out_of_range", f"記録日 {d}: コースが無い")]
    first, last = span
    if first <= d <= last:
        return []
    detail = f"記録日 {d} が {first}（初回の実投与日）〜{last}（受診日）の外"
    return [("entry_out_of_range", detail)]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=JST)


def _check_entry_sequence(patient: SyntheticPatient) -> list[str]:
    """seq は 1..N の通し番号で、記録時刻の順（合成データでは entries.id = seq）。"""
    pid = patient.patient_id
    counts = Counter(e.seq for e in patient.entries)
    duplicated = sorted(seq for seq, n in counts.items() if n > 1)
    if duplicated:  # 順の検査は重複を直してから
        return [
            _issue("duplicate_seq", pid, s, "seq が重複している") for s in duplicated
        ]
    ordered = sorted(patient.entries, key=lambda e: e.seq)
    issues: list[str] = []
    if [e.seq for e in ordered] != list(range(1, len(ordered) + 1)):
        detail = f"seq が 1..{len(ordered)} の通し番号でない"
        issues.append(_issue("seq_order", pid, None, detail))
    for prev, cur in pairwise(ordered):
        if _aware(cur.recorded_at) <= _aware(prev.recorded_at):
            detail = f"記録時刻が seq={prev.seq} より後でない"
            issues.append(_issue("seq_order", pid, cur.seq, detail))
    return issues


# ---------------------------------------------------------------------------
# ラベル
# ---------------------------------------------------------------------------


def _check_label_coverage(
    patient: SyntheticPatient, labels: PatientLabels
) -> list[str]:
    pid = patient.patient_id
    entries = {e.seq: e for e in patient.entries}
    issues: list[str] = []
    labelled: set[int] = set()
    for label in labels.labels:
        seq = label.entry_seq
        entry = entries.get(seq)
        if entry is None:
            issues.append(_issue("label_unknown_entry", pid, seq, "該当する記録が無い"))
        elif not entry.free_text:
            detail = "自由記載の無い記録にラベルがある"
            issues.append(_issue("label_without_free_text", pid, seq, detail))
        elif seq in labelled:
            issues.append(_issue("duplicate_label", pid, seq, "ラベルが2つ以上ある"))
        labelled.add(seq)
    for e in patient.entries:
        if e.free_text and e.seq not in labelled:
            detail = "自由記載にラベルが無い"
            issues.append(_issue("missing_label", pid, e.seq, detail))
    return issues


def _answers_by_date(entries: Iterable[SyntheticEntry]) -> AnswersByDate:
    result: AnswersByDate = {}
    for e in entries:
        result.setdefault(to_jst_date(e.recorded_at), []).extend(e.answers)
    return result


def _check_label(
    label: EntryLabel,
    entry: SyntheticEntry,
    text: str,
    courses: Sequence[SyntheticCourse],
    answers: AnswersByDate,
    term_keys: Mapping[str, str | None],
) -> Found:
    """text は引用を照らす文（mask があれば一次置換後）。"""
    record_date = to_jst_date(entry.recorded_at)
    found: Found = []
    for event in label.events:
        found.extend(_check_event_text(event, text, term_keys))
        found.extend(_check_event_course(event, courses))
        found.extend(_check_event_date(event, record_date))
    same_day = answers.get(record_date, [])
    for contra in label.contradictions:
        found.extend(_check_contradiction(contra, text, same_day, label.events))
    if ("contradiction" in label.hard_case_tags) != bool(label.contradictions):
        detail = "contradiction タグの有無と contradictions の有無が合わない"
        found.append(("contradiction_tag_mismatch", detail))
    return found


def _check_event_text(
    event: LabelEvent, text: str, term_keys: Mapping[str, str | None]
) -> Found:
    found: Found = []
    if not event.source_quote or event.source_quote not in text:
        detail = f"source_quote「{event.source_quote}」が自由記載に無い"
        found.append(("source_quote_mismatch", detail))
    if event.term not in term_keys:
        found.append(("unknown_term", f"「{event.term}」は ctcae_terms に無い"))
    else:
        # FOLFOX に無い質問（手足症候群など）の用語は question_key なしが正しい
        mapped = term_keys[event.term]
        expected = mapped if mapped in FOLFOX_ANSWER_TYPES else None
        if event.question_key != expected:
            detail = f"「{event.term}」の question_key={event.question_key}（期待 {expected}）"
            found.append(("term_question_key_mismatch", detail))
    key = event.question_key
    if key is not None and key not in FOLFOX_ANSWER_TYPES:
        found.append(("unknown_question_key", f"{key} は regimen-folfox の質問に無い"))
    return found


def _check_event_course(event: LabelEvent, courses: Sequence[SyntheticCourse]) -> Found:
    expected = expected_course_day(courses, event.date)
    if expected is None:
        return [("before_first_course", f"{event.date} は最初の実投与日より前")]
    course_no, day = expected
    found: Found = []
    if event.course_no != course_no:
        detail = f"{event.date} の course_no={event.course_no}（期待 {course_no}）"
        found.append(("course_mismatch", detail))
    if event.day != day:
        found.append(("day_mismatch", f"{event.date} の day={event.day}（期待 {day}）"))
    return found


def _check_event_date(event: LabelEvent, record_date: date) -> Found:
    """回想 = 記録日より前の出来事（相対時間のタグがあっても例外にしない）。"""
    where = f"出来事 {event.date}・記録日 {record_date}"
    if event.date > record_date:
        return [("date_after_record", f"記録日より後: {where}")]
    if event.recalled != (event.date < record_date):
        detail = f"recalled={event.recalled} だが {where}（記録日より前なら回想）"
        return [("recalled_mismatch", detail)]
    return []


def _spans(text: str, sub: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = text.find(sub) if sub else -1
    while start != -1:
        spans.append((start, start + len(sub)))
        start = text.find(sub, start + 1)
    return spans


def _overlaps(text: str, a: str, b: str) -> bool:
    """a と b が text の中で1字以上重なる位置にあるか。"""
    return any(
        s1 < e2 and s2 < e1 for s1, e1 in _spans(text, a) for s2, e2 in _spans(text, b)
    )


def _check_contradiction(
    contra: LabelContradiction,
    text: str,
    same_day: Sequence[ClosedAnswer],
    events: Sequence[LabelEvent],
) -> Found:
    found: Found = []
    key, quote = contra.question_key, contra.free_text_quote
    if not quote or quote not in text:
        detail = f"free_text_quote「{quote}」が自由記載に無い"
        found.append(("free_text_quote_mismatch", detail))
    elif not any(
        _overlaps(text, quote, ev.source_quote)
        for ev in events
        if ev.question_key == key
    ):
        detail = f"free_text_quote「{quote}」が {key} の出来事の引用と重ならない"
        found.append(("contradiction_quote_not_event", detail))
    values: list[AnswerValue] = [a.value for a in same_day if a.question_key == key]
    if contra.closed_answer not in values:
        detail = (
            f"{key}={contra.closed_answer} が同じ記録日の"
            f"クローズ回答 {values} に無い"
        )
        found.append(("contradiction_answer_mismatch", detail))
    return found


# ---------------------------------------------------------------------------
# 食い違いの付け漏れ・付け過ぎ
# ---------------------------------------------------------------------------


def _conflicting_statuses(values: set[str], statuses: set[str]) -> frozenset[str]:
    """クローズ回答（values）と食い違う出来事の status。食い違いが無ければ空。

    - 回答が none だけで、出来事に present か improving がある
    - 回答に present か hard があり、出来事が全て absent
    体温の回答（not_measured / measured）はどちらにも当たらない（比べない）。
    """
    if values == {"none"} and statuses & {"present", "improving"}:
        return frozenset({"present", "improving"})
    if values & {"present", "hard"} and statuses == {"absent"}:
        return frozenset({"absent"})
    return frozenset()


def _expected_contradictions(
    labelled: Sequence[LabelledEntry], answers: AnswersByDate
) -> set[tuple[int, str]]:
    """食い違いラベルが要る (記録 seq, question_key)。回想の出来事は比べない。"""
    by_day: dict[tuple[date, str], list[tuple[int, str]]] = {}
    for label, entry in labelled:
        d = to_jst_date(entry.recorded_at)
        for ev in label.events:
            if not ev.recalled and ev.question_key is not None:
                by_day.setdefault((d, ev.question_key), []).append(
                    (entry.seq, ev.status)
                )
    expected: set[tuple[int, str]] = set()
    for (d, key), items in by_day.items():
        values = {a.value for a in answers.get(d, []) if a.question_key == key}
        conflicting = _conflicting_statuses(values, {s for _, s in items})
        expected.update((seq, key) for seq, s in items if s in conflicting)
    return expected


def _check_required_contradictions(
    pid: str, labelled: Sequence[LabelledEntry], answers: AnswersByDate
) -> list[str]:
    expected = _expected_contradictions(labelled, answers)
    actual = {
        (label.entry_seq, c.question_key)
        for label, _ in labelled
        for c in label.contradictions
    }
    missing = [
        _issue("missing_contradiction", pid, seq, f"{key}: 食い違うのにラベルが無い")
        for seq, key in sorted(expected - actual)
    ]
    extra = [
        _issue(
            "not_a_contradiction", pid, seq, f"{key}: 同じ記録日の回答と食い違わない"
        )
        for seq, key in sorted(actual - expected)
    ]
    return [*missing, *extra]


def _check_hard_cases(labels_list: Sequence[PatientLabels]) -> list[str]:
    counts = hard_case_counts(labels_list)
    return [
        f"[hard_case_too_few] 全体: {tag} が {n} 件（{MIN_HARD_CASES} 件以上必要）"
        for tag, n in counts.items()
        if n < MIN_HARD_CASES
    ]

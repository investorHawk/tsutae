"""変換の入力を作る（今コースの選別・通し番号・伏せ字・未処理の記録）。

- 今コースは `course.current_course(courses, visit_date)`。対象は Day1〜
  min(最終日, visit_date) の記録だけ（docs/architecture.md §7）
- 範囲外（Day1 より前・最終日より後・visit_date より後）の記録は**黙って外す**
  （`UnprocessedEntry` にしない。§7 W2b）。件数は logger があれば
  `input_prepared` の decision `out_of_range_count:N` に残す
- 送る記録だけに recorded_at 順で entry_no=1,2,… を振る（外した記録は番号を使わない）
- 自由記載は原文のまま `masking.check_text`（正規化 → 一次 → 二次）に掛ける。改行・
  制御文字・書式文字の正規化は masking の責務で、pipeline では整形しない。masked_texts は
  check_text の masked そのもの（改行を含みうる。H2 の部分一致と食い違わない）
- 外す記録（`UnprocessedEntry(entry_id, reason)`。原文は D6 だけに出る）:
  1. 自由記載に `exclude_literals`（service が渡す仮名ID・受付番号）を含む →
     `known_identifier`。NFKC＋casefold のあと文字・数字以外（区切り記号・空白・
     制御文字・書式文字・長音符）を全て除いて比べる（A023・P_DEMO0001 も一致）。
     一次が `[ID]` に置き換える前の原文で比べる
  2. 二次に掛かった → 最初の規則名
  3. 伏せ字後の文を JSON にした形（依頼文での見え方）で二次に掛かった → 最初の規則名
- 「つらくて書けない」の記録も入れる（too_sick=True、回答・自由記載なし）
- 仮名ID・受付番号は構造の項目に入れない。引数は書き換えない
- 医師の伏せ字（`doctor_masks`: entries.id → DoctorMask。D6 で医師が選んだ区間）が
  ある記録は、**生の原文に区間を当てて `[伏せ字]` にしてから**上の 1〜3 を同じく掛ける
  （区間は原文の位置なので一次の前）。生の記録は変えない（spec 13.3）。区間が原文に
  合わなければ `doctor_mask_invalid` で外す
- 医師が「個人を特定する語は無いことを確かめた」（confirmed_clear）記録は、保存の時点で
  伏せた後もまだ疑われていた区間（DoctorMask.allowed。サーバーが計算）の語だけを許す。
  ほかの検出・known_identifier は許さない。許した語は `allowed_suspects` に入れ、H1 が
  依頼文全体で同じ語だけを無視する。医師の伏せ字を使って送った記録があれば、
  `doctor_masks_applied`（decision `sent:N`）・`doctor_confirmed_sent`（確かめて許した
  記録の数）をログに残す（文面なし。無ければ何も足さない）
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from tsutae.course import build_schedule, current_course, day_of
from tsutae.masking import check_text, detect_identifiers
from tsutae.masking.manual import (
    ManualSpanError,
    apply_spans,
    prompt_form,
    without_allowed,
)
from tsutae.pipeline.logs import EventLogger
from tsutae.schemas import (
    Course,
    CourseSchedule,
    DoctorMask,
    Entry,
    MaskedEntry,
    PipelineInput,
    PreparedInput,
    RegimenSkill,
    ReportFormatSkill,
    UnprocessedEntry,
)

__all__ = [
    "REASON_DOCTOR_MASK_INVALID",
    "REASON_KNOWN_IDENTIFIER",
    "MaskOutcome",
    "PrepareInputError",
    "check_doctor_masks",
    "doctor_masked_source",
    "has_known_literal",
    "mask_entry_text",
    "mask_free_text",
    "prepare_input",
]

REASON_KNOWN_IDENTIFIER = "known_identifier"
REASON_DOCTOR_MASK_INVALID = "doctor_mask_invalid"
INPUT_PREPARED_EVENT = "input_prepared"
DOCTOR_MASKS_EVENT = "doctor_masks_applied"
DOCTOR_CONFIRMED_EVENT = "doctor_confirmed_sent"
# 区切りに使われる長音符（Lm なので文字として残ってしまう）。半角 ｰ は NFKC で ー
_PROLONGED_MARKS = frozenset("ー")


class PrepareInputError(ValueError):
    """入力を作れない。`code` は短い英字（no_current_course / patient_mismatch）。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _check_same_patient(courses: Sequence[Course], entries: Sequence[Entry]) -> None:
    patient_ids = {c.patient_id for c in courses} | {e.patient_id for e in entries}
    if len(patient_ids) > 1:
        raise PrepareInputError(
            "patient_mismatch", "別の患者の記録・コースが混ざっている"
        )


def _in_course(
    entries: Sequence[Entry],
    schedule: CourseSchedule,
    courses: Sequence[Course],
    until: date,
) -> list[tuple[Entry, int]]:
    """今コースの Day1〜until の記録を (記録, Day) で recorded_at 順に返す。"""
    picked = []
    for entry in sorted(entries, key=lambda e: (e.recorded_at, e.id)):
        if entry.record_date > until:
            continue
        day = day_of(entry.record_date, schedule, courses=courses)
        if day is not None:
            picked.append((entry, day))
    return picked


def _masked_entry(
    entry: Entry, entry_no: int, day: int, masked: str | None
) -> MaskedEntry:
    return MaskedEntry(
        entry_no=entry_no,
        record_date=entry.record_date,
        day=day,
        by_proxy=entry.by_proxy,
        too_sick=entry.kind == "too_sick",
        answers=list(entry.answers),
        masked_free_text=masked,
    )


@dataclass(frozen=True)
class MaskOutcome:
    """伏せ字の結果。reason があれば送らない。allowed は確かめて許した語（H1 に渡す）。"""

    masked: str | None
    reason: str | None
    allowed: tuple[str, ...] = ()


def doctor_masked_source(text: str, doctor_mask: DoctorMask | None) -> str | None:
    """生の原文に医師の区間を当てた文（区間が無ければ原文）。合わなければ None。"""
    if doctor_mask is None:
        return text
    try:
        return apply_spans(text, [(s.start, s.end) for s in doctor_mask.spans])
    except ManualSpanError:
        return None


def _allowed_spans(
    masked: str, doctor_mask: DoctorMask | None
) -> tuple[tuple[int, int], ...] | None:
    """確かめた記録の許す区間（伏せた後の文の位置）。範囲の外なら None。"""
    if doctor_mask is None or not doctor_mask.confirmed_clear:
        return ()
    spans = tuple((s.start, s.end) for s in doctor_mask.allowed)
    if any(end > len(masked) or end <= start for start, end in spans):
        return None
    return spans


def mask_entry_text(
    text: str | None, doctor_mask: DoctorMask | None = None
) -> MaskOutcome:
    """医師の区間 → check_text → 依頼文の形での二次。exclude_literals の照合は除く。

    doctor_mask が無ければ従来の mask_free_text と同じ結果（allowed は空）。
    """
    if not text or not text.strip():
        return MaskOutcome(None, None)
    source = doctor_masked_source(text, doctor_mask)
    if source is None:
        return MaskOutcome(None, REASON_DOCTOR_MASK_INVALID)
    check = check_text(source)
    spans = _allowed_spans(check.masked, doctor_mask)
    if spans is None:
        return MaskOutcome(None, REASON_DOCTOR_MASK_INVALID)
    remaining = [
        d
        for d in check.detections
        if not any(s <= d.start and d.end <= e for s, e in spans)
    ]
    if remaining:
        return MaskOutcome(None, remaining[0].rule)
    if not check.masked.strip():
        return MaskOutcome(None, None)
    allowed = tuple(check.masked[s:e] for s, e in spans)
    in_prompt = json.dumps(check.masked, ensure_ascii=False)
    found = without_allowed(
        in_prompt, detect_identifiers(in_prompt), [prompt_form(a) for a in allowed]
    )
    if found:
        return MaskOutcome(None, found[0].rule)
    return MaskOutcome(check.masked, None, allowed)


def mask_free_text(
    text: str | None, doctor_mask: DoctorMask | None = None
) -> tuple[str | None, str | None]:
    """(伏せ字後の文, 外す理由)。理由があれば送らない。空の文は (None, None)。

    prepare_input と同じ手順（exclude_literals の照合を除く）。report.gate もこれを呼ぶ
    （写しを持たない。正規化して空になる文を片方だけ '' にすると entry_mismatch）。
    医師の伏せ字があれば mask_entry_text と同じく先に当てる。
    """
    outcome = mask_entry_text(text, doctor_mask)
    return outcome.masked, outcome.reason


def _fold(text: str) -> str:
    """識別子の比較用: NFKC → casefold → 文字（L 系）と数字（N 系）だけを残す。

    記号・句読点（P 系: ハイフン・下線・中黒・ピリオド・スラッシュ等、S 系）、制御・
    書式文字（C 系）、空白（Z 系）と長音符「ー」は全て除く。`A023`・`A・023`・
    `P_DEMO0001`・`P-\nDEMO0001` を `A-023`・`P-DEMO0001` と同じに扱う（一次・二次の
    正規表現は区切りの崩れた形を拾いきれない）。照合する側の文字列も同じく畳む。
    誤って一致した記録は送らないだけ（安全側）。
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if _is_id_char(ch))


def _is_id_char(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LN" and ch not in _PROLONGED_MARKS


def _fold_literals(literals: Sequence[str]) -> tuple[str, ...]:
    if isinstance(literals, str) or not isinstance(literals, Sequence):
        raise TypeError("exclude_literals は文字列の列（str そのものは不可）")
    if not all(isinstance(lit, str) for lit in literals):
        raise TypeError("exclude_literals の要素は str")
    return tuple(folded for folded in map(_fold, literals) if folded)


def _has_literal(text: str, folded_literals: tuple[str, ...]) -> bool:
    folded = _fold(text)
    return any(lit in folded for lit in folded_literals)


def has_known_literal(text: str, literals: Sequence[str]) -> bool:
    """text に仮名ID・受付番号（literals）を含むか（prepare_input と同じ畳み方）。"""
    return _has_literal(text, _fold_literals(literals))


def check_doctor_masks(
    doctor_masks: Mapping[int, DoctorMask] | None,
) -> Mapping[int, DoctorMask]:
    """entries.id → DoctorMask の対応表を検査して写す（None は空）。"""
    if doctor_masks is None:
        return {}
    if not isinstance(doctor_masks, Mapping):
        raise TypeError("doctor_masks は entries.id → DoctorMask の対応表")
    for key, value in doctor_masks.items():
        if isinstance(key, bool) or not isinstance(key, int):
            raise TypeError("doctor_masks のキーは entries.id（int）")
        if not isinstance(value, DoctorMask):
            raise TypeError("doctor_masks の値は DoctorMask")
    return dict(doctor_masks)


def _outcome(
    text: str, doctor_mask: DoctorMask | None, folded_literals: tuple[str, ...]
) -> MaskOutcome:
    """記録1件の伏せ字（医師の区間を当てた後の文で仮名ID・受付番号を照合する）。"""
    source = doctor_masked_source(text, doctor_mask)
    if source is None:
        return MaskOutcome(None, REASON_DOCTOR_MASK_INVALID)
    if _has_literal(source, folded_literals):
        return MaskOutcome(None, REASON_KNOWN_IDENTIFIER)
    return mask_entry_text(text, doctor_mask)


@dataclass
class _Selected:
    entries: list[MaskedEntry]
    entry_ids: dict[int, int]
    masked_texts: dict[int, str]
    unprocessed: list[UnprocessedEntry]
    allowed: set[str]
    doctor_sent: int = 0
    confirmed_sent: int = 0


def _select(
    picked: list[tuple[Entry, int]],
    folded_literals: tuple[str, ...],
    doctor_masks: Mapping[int, DoctorMask],
) -> _Selected:
    """伏せ字を掛け、送る記録に entry_no を振る。外す記録は理由つきで返す。"""
    out = _Selected([], {}, {}, [], set())
    for entry, day in picked:
        masked: str | None = None
        doctor_mask = doctor_masks.get(entry.id)
        if entry.free_text:
            outcome = _outcome(entry.free_text, doctor_mask, folded_literals)
            if outcome.reason is not None:
                out.unprocessed.append(
                    UnprocessedEntry(entry_id=entry.id, reason=outcome.reason)
                )
                continue
            masked = outcome.masked
            out.allowed.update(outcome.allowed)
            if doctor_mask is not None:
                out.doctor_sent += 1
                out.confirmed_sent += 1 if outcome.allowed else 0
        entry_no = len(out.entries) + 1
        out.entries.append(_masked_entry(entry, entry_no, day, masked))
        out.entry_ids[entry_no] = entry.id
        if masked:
            out.masked_texts[entry_no] = masked
    return out


def _log_doctor_masks(logger: EventLogger, selected: _Selected) -> None:
    if selected.doctor_sent:
        logger.event(DOCTOR_MASKS_EVENT, decision=f"sent:{selected.doctor_sent}")
    if selected.confirmed_sent:
        logger.event(DOCTOR_CONFIRMED_EVENT, decision=f"sent:{selected.confirmed_sent}")


def _schedule_for(
    courses: Sequence[Course], regimen_skill: RegimenSkill, visit_date: date
) -> CourseSchedule:
    course = current_course(courses, visit_date)
    if course is None:
        raise PrepareInputError("no_current_course", "受診日より前の実投与日が無い")
    return build_schedule(
        courses,
        course.course_no,
        regimen_skill.cycle_days,
        regimen_skill.pump_removal_day,
    )


def prepare_input(
    *,
    courses: Sequence[Course],
    entries: Sequence[Entry],
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    visit_date: date,
    exclude_literals: Sequence[str] = (),
    doctor_masks: Mapping[int, DoctorMask] | None = None,
    logger: EventLogger | None = None,
) -> PreparedInput:
    """受診日の今コースの記録から、Claude に送る入力を作る。"""
    folded_literals = _fold_literals(exclude_literals)
    masks = check_doctor_masks(doctor_masks)
    _check_same_patient(courses, entries)
    schedule = _schedule_for(courses, regimen_skill, visit_date)
    until = min(schedule.last_day_date, visit_date)
    picked = _in_course(entries, schedule, courses, until)
    selected = _select(picked, folded_literals, masks)
    if logger is not None:
        out_of_range = len(entries) - len(picked)
        logger.event(
            INPUT_PREPARED_EVENT, decision=f"out_of_range_count:{out_of_range}"
        )
        _log_doctor_masks(logger, selected)
    return PreparedInput(
        input=PipelineInput(
            regimen=regimen_skill.regimen,
            regimen_skill_version=regimen_skill.skill_version,
            report_skill_version=report_skill.skill_version,
            schedule=schedule,
            questions=list(regimen_skill.questions),
            entries=selected.entries,
        ),
        entry_ids=selected.entry_ids,
        masked_texts=selected.masked_texts,
        unprocessed=selected.unprocessed,
        allowed_suspects=sorted(selected.allowed),
    )

"""評価の対象（role=eval の患者の各コースと、その基準日）。症例は全て合成。

基準日（visit_date）は各コースの最終日: 次コースの実投与日の前日。最後のコースは
患者の受診予定日（patient.visit_date）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

from tsutae.schemas import PatientLabels, SyntheticPatient
from tsutae.synthetic import DATASET_NAMES, all_patients

PatientPair = tuple[SyntheticPatient, PatientLabels]


@dataclass(frozen=True)
class EvalCase:
    patient: SyntheticPatient
    labels: PatientLabels
    course_no: int
    visit_date: date


def course_visit_dates(patient: SyntheticPatient) -> list[tuple[int, date]]:
    """(course_no, visit_date)。visit_date = 次コース実投与日の前日、最後は受診日。"""
    ordered = sorted(patient.courses, key=lambda c: c.course_no)
    if not ordered:
        return []
    middle = [
        (cur.course_no, nxt.infusion_date - timedelta(days=1))
        for cur, nxt in pairwise(ordered)
    ]
    return [*middle, (ordered[-1].course_no, patient.visit_date)]


def _eval_pairs(data_dir: Path) -> list[tuple[str, SyntheticPatient, PatientLabels]]:
    pairs = all_patients(data_dir)
    named = zip(DATASET_NAMES, pairs, strict=True)
    return [(name, p, labels) for name, (p, labels) in named if p.role == "eval"]


def select_patients(data_dir: Path, wanted: Sequence[str] | None) -> list[PatientPair]:
    """role=eval の患者。wanted は患者ID かファイル名（eval_patient_a 等）。"""
    evals = _eval_pairs(data_dir)
    if not wanted:
        return [(p, labels) for _, p, labels in evals]
    known = {key: p.patient_id for name, p, _ in evals for key in (name, p.patient_id)}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise ValueError(f"評価用の患者に無い: {', '.join(unknown)}")
    ids = {known[w] for w in wanted}
    return [(p, labels) for _, p, labels in evals if p.patient_id in ids]


def eval_cases(data_dir: Path, patients: Sequence[str] | None = None) -> list[EvalCase]:
    return [
        EvalCase(patient=p, labels=labels, course_no=no, visit_date=visit)
        for p, labels in select_patients(data_dir, patients)
        for no, visit in course_visit_dates(p)
    ]

from datetime import date

from tsutae import dataset
from tsutae.config import SYNTHETIC_DIR
from tsutae.synthetic import load_patient


def _demo():
    return load_patient(SYNTHETIC_DIR / "demo_patient.json")


def test_to_entries_keeps_seq_as_id_and_order() -> None:
    patient = _demo()
    entries = dataset.to_entries(patient)
    assert [e.id for e in entries] == [e.seq for e in patient.entries]
    assert all(e.patient_id == patient.patient_id for e in entries)
    assert entries == sorted(entries, key=lambda e: e.recorded_at)


def test_to_entries_kind_and_record_date() -> None:
    entries = dataset.to_entries(_demo())
    kinds = {e.kind for e in entries}
    assert "too_sick" in kinds
    for e in entries:
        assert e.record_date == e.recorded_at.date()
        if e.kind == "too_sick":
            assert not e.answers and e.free_text is None
        if e.kind == "mixed":
            assert e.answers and e.free_text


def test_to_courses_matches_file() -> None:
    patient = _demo()
    courses = dataset.to_courses(patient)
    assert [c.course_no for c in courses] == [1, 2, 3]
    assert courses[1].infusion_date == date(2026, 10, 13)
    assert courses[1].planned_date == date(2026, 10, 11)
    assert all(c.patient_id == patient.patient_id for c in courses)


def test_to_entry_create_roundtrip() -> None:
    patient = _demo()
    for src in patient.entries:
        ec = dataset.to_entry_create(src)
        assert ec.too_sick == src.too_sick
        assert ec.free_text == (src.free_text.strip() if src.free_text else None)

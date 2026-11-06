"""tsutae.synthetic の読み込みと検査のテスト。

小さな合成データを tmp_path に書き、validate_dataset が違反ごとに見つけることを確かめる。
data/synthetic の実データの検査は test_synthetic_real.py。
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tsutae import config, synthetic
from tsutae.schemas import PatientLabels, SyntheticPatient

PID = "P-TEST0001"


def _at(day: str, hh: int = 20) -> str:
    return f"{day}T{hh:02d}:00:00+09:00"


def _event(
    d: str,
    day: int | None,
    course_no: int,
    term: str,
    status: str,
    quote: str,
    question_key: str | None = None,
    recalled: bool = False,
) -> dict[str, Any]:
    return {
        "date": d,
        "day": day,
        "course_no": course_no,
        "term": term,
        "question_key": question_key,
        "status": status,
        "source_quote": quote,
        "recalled": recalled,
    }


def _base_patient() -> dict[str, Any]:
    """C1 = 9/1、C2 = 9/15。全ての検査を通る最小の患者。"""
    return {
        "patient_id": PID,
        "role": "eval",
        "regimen": "FOLFOX",
        "visit_date": "2026-09-28",
        "reception_no": "T-001",
        "courses": [
            {"course_no": 1, "infusion_date": "2026-09-01"},
            {
                "course_no": 2,
                "infusion_date": "2026-09-15",
                "planned_date": "2026-09-15",
            },
        ],
        "entries": [
            {"seq": 1, "recorded_at": _at("2026-09-03"), "too_sick": True},
            {
                "seq": 2,
                "recorded_at": _at("2026-09-05"),
                "answers": [
                    {"question_key": "diarrhea", "value": "none"},
                    {"question_key": "fever", "value": "measured", "temperature": 36.8},
                ],
                "free_text": "夕方に下痢が2回あった。吐き気はなかった。",
            },
            {
                "seq": 3,
                "recorded_at": _at("2026-09-08"),
                "free_text": "点滴の次の日から手足のしびれが続いている。",
            },
            {
                "seq": 4,
                "recorded_at": _at("2026-09-10"),
                "by_proxy": True,
                "free_text": "しびれはだいぶ楽になってきた。",
            },
            {
                "seq": 5,
                "recorded_at": _at("2026-09-17"),
                "answers": [{"question_key": "diarrhea", "value": "none"}],
                "free_text": "今日も少し下痢っぽい。口内炎はできていない。",
            },
            {
                "seq": 6,
                "recorded_at": _at("2026-09-20"),
                "free_text": "おとといは熱っぽかった。ポンプを外した日から口の中が痛い。",
            },
            {
                "seq": 7,
                "recorded_at": _at("2026-09-22"),
                "free_text": "しびれは少し残るが軽い。",
            },
        ],
    }


def _base_labels() -> dict[str, Any]:
    numb = "末梢神経障害"
    return {
        "patient_id": PID,
        "labels": [
            {
                "entry_seq": 2,
                "events": [
                    _event(
                        "2026-09-05",
                        5,
                        1,
                        "下痢",
                        "present",
                        "下痢が2回あった",
                        "diarrhea",
                    ),
                    _event(
                        "2026-09-05",
                        5,
                        1,
                        "悪心",
                        "absent",
                        "吐き気はなかった",
                        "nausea_appetite",
                    ),
                ],
                "contradictions": [
                    {
                        "question_key": "diarrhea",
                        "closed_answer": "none",
                        "free_text_quote": "下痢が2回あった",
                    }
                ],
                "hard_case_tags": ["contradiction", "negation"],
            },
            {
                "entry_seq": 3,
                "events": [
                    _event(
                        "2026-09-02",
                        2,
                        1,
                        numb,
                        "present",
                        "点滴の次の日から手足のしびれが続いている",
                        "numbness",
                        recalled=True,
                    )
                ],
                "hard_case_tags": ["relative_time"],
            },
            {
                "entry_seq": 4,
                "events": [
                    _event(
                        "2026-09-10",
                        10,
                        1,
                        numb,
                        "improving",
                        "しびれはだいぶ楽になってきた",
                        "numbness",
                    )
                ],
                "hard_case_tags": ["mild_improving"],
            },
            {
                "entry_seq": 5,
                "events": [
                    _event(
                        "2026-09-17",
                        3,
                        2,
                        "下痢",
                        "present",
                        "少し下痢っぽい",
                        "diarrhea",
                    ),
                    _event(
                        "2026-09-17",
                        3,
                        2,
                        "口内炎",
                        "absent",
                        "口内炎はできていない",
                        "stomatitis",
                    ),
                ],
                "contradictions": [
                    {
                        "question_key": "diarrhea",
                        "closed_answer": "none",
                        "free_text_quote": "少し下痢っぽい",
                    }
                ],
                "hard_case_tags": ["contradiction", "negation"],
            },
            {
                "entry_seq": 6,
                "events": [
                    _event(
                        "2026-09-18",
                        4,
                        2,
                        "発熱",
                        "present",
                        "おとといは熱っぽかった",
                        "fever",
                        recalled=True,
                    ),
                    _event(
                        "2026-09-17",
                        3,
                        2,
                        "口腔痛",
                        "present",
                        "ポンプを外した日から口の中が痛い",
                        "stomatitis",
                        recalled=True,
                    ),
                ],
                "hard_case_tags": ["relative_time"],
            },
            {
                "entry_seq": 7,
                "events": [
                    _event(
                        "2026-09-22",
                        8,
                        2,
                        numb,
                        "improving",
                        "しびれは少し残るが軽い",
                        "numbness",
                    )
                ],
                "hard_case_tags": ["mild_improving"],
            },
        ],
    }


def _label(labels: dict[str, Any], seq: int) -> dict[str, Any]:
    return next(x for x in labels["labels"] if x["entry_seq"] == seq)


def _entry(patient: dict[str, Any], seq: int) -> dict[str, Any]:
    return next(x for x in patient["entries"] if x["seq"] == seq)


def _insert_entry(
    patient: dict[str, Any], labels: dict[str, Any], entry: dict[str, Any]
) -> None:
    """記録を足し、記録時刻の順に seq を振り直す（ラベルの entry_seq も追従）。"""
    ordered = sorted([*patient["entries"], entry], key=lambda e: e["recorded_at"])
    renumber = {e["seq"]: i for i, e in enumerate(ordered, 1) if e is not entry}
    patient["entries"] = [{**e, "seq": i} for i, e in enumerate(ordered, 1)]
    for label in labels["labels"]:
        label["entry_seq"] = renumber[label["entry_seq"]]


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _load_pair(
    tmp_path: Path, patient: dict[str, Any], labels: dict[str, Any]
) -> tuple[SyntheticPatient, PatientLabels]:
    p = synthetic.load_patient(_write(tmp_path / "patient.json", patient))
    lb = synthetic.load_labels(_write(tmp_path / "labels.json", labels))
    return p, lb


def _validate(
    tmp_path: Path, patient: dict[str, Any], labels: dict[str, Any]
) -> list[str]:
    return synthetic.validate_dataset([_load_pair(tmp_path, patient, labels)])


def _codes(issues: list[str]) -> set[str]:
    codes = set()
    for issue in issues:
        m = re.match(r"^\[([a-z_]+)\]", issue)
        assert m, f"問題の文字列がコードで始まっていない: {issue}"
        codes.add(m.group(1))
    return codes


# ---------------------------------------------------------------------------
# 読み込み・集計
# ---------------------------------------------------------------------------


def test_base_dataset_is_valid(tmp_path: Path) -> None:
    assert _validate(tmp_path, _base_patient(), _base_labels()) == []


def test_load_patient_and_labels(tmp_path: Path) -> None:
    patient, labels = _load_pair(tmp_path, _base_patient(), _base_labels())
    assert patient.patient_id == PID
    assert len(patient.entries) == 7
    assert patient.entries[0].recorded_at.utcoffset() == timedelta(hours=9)
    assert [x.entry_seq for x in labels.labels] == [2, 3, 4, 5, 6, 7]


def test_load_patient_rejects_schema_violation(tmp_path: Path) -> None:
    patient = _base_patient()
    patient["regimen"] = "XELOX"
    with pytest.raises(ValueError):
        synthetic.load_patient(_write(tmp_path / "p.json", patient))


def test_hard_case_counts_has_all_tags() -> None:
    labels = PatientLabels.model_validate(_base_labels())
    counts = synthetic.hard_case_counts([labels])
    assert counts == {
        "contradiction": 2,
        "mild_improving": 2,
        "relative_time": 2,
        "negation": 2,
    }
    assert synthetic.hard_case_counts([]) == dict.fromkeys(counts, 0)


def test_expected_course_day_boundaries() -> None:
    courses = SyntheticPatient.model_validate(_base_patient()).courses
    assert synthetic.expected_course_day(courses, date(2026, 9, 1)) == (1, 1)
    # 次コース実投与日の前日までが今コース
    assert synthetic.expected_course_day(courses, date(2026, 9, 14)) == (1, 14)
    assert synthetic.expected_course_day(courses, date(2026, 9, 15)) == (2, 1)
    # 最終コースは Day15 以降も数える
    assert synthetic.expected_course_day(courses, date(2026, 10, 1)) == (2, 17)
    assert synthetic.expected_course_day(courses, date(2026, 8, 31)) is None


def test_load_terms_reads_terms() -> None:
    terms = synthetic.load_terms()
    names = [t["term"] for t in terms]
    assert "下痢" in names
    assert len(names) == len(set(names))
    assert all("question_key" in t for t in terms)


def test_load_terms_rejects_broken_file(tmp_path: Path) -> None:
    path = _write(tmp_path / "terms.json", {"terms": [{"question_key": "a"}]})
    with pytest.raises(ValueError):
        synthetic.load_terms(path)


def test_all_patients_reads_three_pairs(tmp_path: Path) -> None:
    for i, name in enumerate(synthetic.DATASET_NAMES):
        pid = f"P-TEST000{i}"
        patient = {**_base_patient(), "patient_id": pid}
        _write(tmp_path / f"{name}.json", patient)
        _write(tmp_path / f"labels_{name}.json", {**_base_labels(), "patient_id": pid})
    pairs = synthetic.all_patients(tmp_path)
    assert [p.patient_id for p, _ in pairs] == [
        "P-TEST0000",
        "P-TEST0001",
        "P-TEST0002",
    ]
    assert all(p.patient_id == lb.patient_id for p, lb in pairs)


def test_all_patients_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        synthetic.all_patients(tmp_path)


def test_validate_dataset_defaults_to_synthetic_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i, name in enumerate(synthetic.DATASET_NAMES):
        pid = f"P-TEST000{i}"
        _write(tmp_path / f"{name}.json", {**_base_patient(), "patient_id": pid})
        _write(tmp_path / f"labels_{name}.json", {**_base_labels(), "patient_id": pid})
    monkeypatch.setattr(config, "SYNTHETIC_DIR", tmp_path)
    assert synthetic.validate_dataset() == []


# ---------------------------------------------------------------------------
# 違反ごとの検出
# ---------------------------------------------------------------------------


def test_detects_duplicate_seq(tmp_path: Path) -> None:
    patient = _base_patient()
    patient["entries"].append(dict(_entry(patient, 1)))
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {"duplicate_seq"}


def test_detects_naive_recorded_at(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 1)["recorded_at"] = "2026-09-03T20:00:00"
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {"naive_recorded_at"}


@pytest.mark.parametrize(
    ("seq", "code"), [(99, "label_unknown_entry"), (1, "label_without_free_text")]
)
def test_detects_label_for_bad_entry(tmp_path: Path, seq: int, code: str) -> None:
    labels = _base_labels()
    labels["labels"].append({"entry_seq": seq})
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == {code}


def test_detects_duplicate_label(tmp_path: Path) -> None:
    labels = _base_labels()
    labels["labels"].append(dict(_label(labels, 7), hard_case_tags=[]))
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == {"duplicate_label"}


def test_detects_free_text_without_label(tmp_path: Path) -> None:
    patient = _base_patient()
    patient["entries"].append(
        {"seq": 8, "recorded_at": _at("2026-09-23"), "free_text": "特に変わりなし。"}
    )
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {"missing_label"}


@pytest.mark.parametrize(
    ("seq", "changes", "expected"),
    [
        (4, {"source_quote": "しびれはすっかり消えた"}, {"source_quote_mismatch"}),
        (4, {"source_quote": ""}, {"source_quote_mismatch"}),
        (4, {"term": "しびれ"}, {"unknown_term"}),
        (7, {"question_key": "diarrhea"}, {"term_question_key_mismatch"}),
        (7, {"question_key": None}, {"term_question_key_mismatch"}),
        (4, {"day": 9}, {"day_mismatch"}),
        (7, {"course_no": 1}, {"course_mismatch"}),
        (3, {"date": "2026-08-30", "day": None}, {"before_first_course"}),
        (3, {"date": "2026-09-09", "day": 9}, {"date_after_record"}),
        # 回想 = 記録日より前の出来事（相対時間のタグがあっても例外にしない）
        (6, {"date": "2026-09-20", "day": 6}, {"recalled_mismatch"}),
        (4, {"date": "2026-09-09", "day": 9}, {"recalled_mismatch"}),
        (3, {"recalled": False}, {"recalled_mismatch"}),  # 点滴の次の日から
        (6, {"recalled": False}, {"recalled_mismatch"}),  # おとといは熱っぽかった
    ],
    ids=[
        "quote",
        "empty_quote",
        "term",
        "term_key",
        "term_key_none",
        "day",
        "course",
        "before_c1",
        "after_record",
        "recalled_on_record_date",
        "earlier_not_recalled",
        "relative_not_recalled",
        "ototoi_not_recalled",
    ],
)
def test_detects_bad_event(
    tmp_path: Path, seq: int, changes: dict[str, Any], expected: set[str]
) -> None:
    labels = _base_labels()
    _label(labels, seq)["events"][0].update(changes)
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == expected


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"free_text_quote": "下痢が3回あった"}, {"free_text_quote_mismatch"}),
        ({"free_text_quote": "吐き気はなかった"}, {"contradiction_quote_not_event"}),
        ({"free_text_quote": "夕方に下痢"}, set()),  # 出来事の引用と一部重なればよい
        ({"closed_answer": "present"}, {"contradiction_answer_mismatch"}),
        # 下痢の食い違いが消え、口の食い違いは根拠の回答も引用の出来事も無い
        (
            {"question_key": "stomatitis"},
            {
                "contradiction_answer_mismatch",
                "contradiction_quote_not_event",
                "missing_contradiction",
                "not_a_contradiction",
            },
        ),
    ],
    ids=["quote", "quote_other_key", "quote_partial", "answer", "key"],
)
def test_contradiction_fields(
    tmp_path: Path, changes: dict[str, Any], expected: set[str]
) -> None:
    labels = _base_labels()
    _label(labels, 2)["contradictions"][0].update(changes)
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == expected


def test_contradiction_matches_answer_in_other_entry_same_day(tmp_path: Path) -> None:
    patient, labels = _base_patient(), _base_labels()
    entry = _entry(patient, 2)
    entry["answers"] = [a for a in entry["answers"] if a["question_key"] != "diarrhea"]
    _insert_entry(
        patient,
        labels,
        {
            "seq": 0,
            "recorded_at": _at("2026-09-05", 8),
            "answers": [{"question_key": "diarrhea", "value": "none"}],
        },
    )
    assert _validate(tmp_path, patient, labels) == []


def test_detects_too_sick_with_answers(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 1)["answers"] = [{"question_key": "diarrhea", "value": "hard"}]
    issues = _validate(tmp_path, patient, _base_labels())
    assert _codes(issues) == {"entry_invalid"}
    assert "too_sick" in issues[0]


def test_detects_too_sick_with_free_text(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 1)["free_text"] = "とてもつらい"
    assert "entry_invalid" in _codes(_validate(tmp_path, patient, _base_labels()))


def test_detects_too_few_hard_cases(tmp_path: Path) -> None:
    labels = _base_labels()
    _label(labels, 7)["hard_case_tags"] = []
    issues = _validate(tmp_path, _base_patient(), labels)
    assert _codes(issues) == {"hard_case_too_few"}
    assert "mild_improving" in issues[0]


def test_detects_wrong_skill_version(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 3)["skill_version"] = "regimen-folfox@2"
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {
        "skill_version_mismatch"
    }


def test_detects_patient_id_mismatch(tmp_path: Path) -> None:
    labels = _base_labels()
    labels["patient_id"] = "P-OTHER001"
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == {
        "patient_id_mismatch"
    }


# ---------------------------------------------------------------------------
# 食い違いラベルの正しさ（同じ記録日のクローズ回答と、回想でない出来事を比べる）
# ---------------------------------------------------------------------------


def _contra(key: str, value: str, quote: str) -> dict[str, Any]:
    return {"question_key": key, "closed_answer": value, "free_text_quote": quote}


def test_detects_contradiction_tag_without_contradictions(tmp_path: Path) -> None:
    labels = _base_labels()
    _label(labels, 7)["hard_case_tags"].append("contradiction")
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == {
        "contradiction_tag_mismatch"
    }


def test_detects_contradictions_without_tag(tmp_path: Path) -> None:
    labels = _base_labels()
    _label(labels, 2)["hard_case_tags"] = ["negation"]
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == {
        "contradiction_tag_mismatch",
        "hard_case_too_few",
    }


def test_detects_missing_contradiction_for_present(tmp_path: Path) -> None:
    labels = _base_labels()
    _label(labels, 2).update({"contradictions": [], "hard_case_tags": ["negation"]})
    assert _codes(_validate(tmp_path, _base_patient(), labels)) == {
        "missing_contradiction",
        "hard_case_too_few",
    }


def test_detects_missing_contradiction_for_improving(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 4)["answers"] = [{"question_key": "numbness", "value": "none"}]
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {
        "missing_contradiction"
    }


def test_recalled_event_is_not_compared_with_answers(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 3)["answers"] = [{"question_key": "numbness", "value": "none"}]
    assert _validate(tmp_path, patient, _base_labels()) == []


def test_detects_absent_marked_as_contradiction(tmp_path: Path) -> None:
    patient, labels = _base_patient(), _base_labels()
    _entry(patient, 2)["answers"].append(
        {"question_key": "nausea_appetite", "value": "none"}
    )
    _label(labels, 2)["contradictions"].append(
        _contra("nausea_appetite", "none", "吐き気はなかった")
    )
    assert _codes(_validate(tmp_path, patient, labels)) == {"not_a_contradiction"}


def test_detects_missing_contradiction_for_absent_vs_hard(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 5)["answers"].append(
        {"question_key": "stomatitis", "value": "hard"}
    )
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {
        "missing_contradiction"
    }


def test_absent_vs_hard_with_contradiction_is_valid(tmp_path: Path) -> None:
    patient, labels = _base_patient(), _base_labels()
    _entry(patient, 5)["answers"].append(
        {"question_key": "stomatitis", "value": "hard"}
    )
    _label(labels, 5)["contradictions"].append(
        _contra("stomatitis", "hard", "口内炎はできていない")
    )
    assert _validate(tmp_path, patient, labels) == []


def test_fever_not_measured_is_not_compared(tmp_path: Path) -> None:
    patient, labels = _base_patient(), _base_labels()
    entry = _entry(patient, 7)
    entry["free_text"] = "しびれは少し残るが軽い。少し熱っぽい。"
    entry["answers"] = [{"question_key": "fever", "value": "not_measured"}]
    _label(labels, 7)["events"].append(
        _event("2026-09-22", 8, 2, "発熱", "present", "少し熱っぽい", "fever")
    )
    assert _validate(tmp_path, patient, labels) == []


# ---------------------------------------------------------------------------
# 回想 = 出来事の暦日が記録日より前（相対時間のタグがあっても例外にしない）
# ---------------------------------------------------------------------------


def test_detects_today_event_dated_earlier_in_relative_label(tmp_path: Path) -> None:
    patient, labels = _base_patient(), _base_labels()
    _entry(patient, 6)["free_text"] += "きょうは熱っぽい。"
    _label(labels, 6)["events"].append(
        _event("2026-09-16", 2, 2, "発熱", "present", "きょうは熱っぽい", "fever")
    )
    assert _codes(_validate(tmp_path, patient, labels)) == {"recalled_mismatch"}


# ---------------------------------------------------------------------------
# 記録の中身（EntryCreate と同じ不変条件・質問集・期間・seq の順）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (
            {"question_key": "numbness", "value": "measured", "temperature": 36.0},
            "answer_type_mismatch",
        ),
        ({"question_key": "fever", "value": "hard"}, "answer_type_mismatch"),
        ({"question_key": "hand_foot", "value": "present"}, "unknown_question_key"),
        ({"question_key": "diarrhea", "value": "none"}, "entry_invalid"),  # 重複
    ],
)
def test_detects_bad_answer(tmp_path: Path, answer: dict[str, Any], code: str) -> None:
    patient = _base_patient()
    _entry(patient, 5)["answers"].append(answer)
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {code}


def test_detects_empty_entry(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 1)["too_sick"] = False
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {"entry_invalid"}


@pytest.mark.parametrize(
    ("day", "expected"),
    [("2026-10-30", {"entry_out_of_range"}), ("2026-09-28", set())],
)
def test_entry_after_visit_date(tmp_path: Path, day: str, expected: set[str]) -> None:
    patient = _base_patient()
    patient["entries"].append(
        {
            "seq": 8,
            "recorded_at": _at(day),
            "answers": [{"question_key": "diarrhea", "value": "none"}],
        }
    )
    assert _codes(_validate(tmp_path, patient, _base_labels())) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [("2026-08-20", {"entry_out_of_range"}), ("2026-09-01", set())],
)
def test_entry_before_first_infusion(
    tmp_path: Path, day: str, expected: set[str]
) -> None:
    patient = _base_patient()
    _entry(patient, 1)["recorded_at"] = _at(day)
    assert _codes(_validate(tmp_path, patient, _base_labels())) == expected


def test_detects_seq_gap(tmp_path: Path) -> None:
    patient, labels = _base_patient(), _base_labels()
    _entry(patient, 7)["seq"] = 70
    _label(labels, 7)["entry_seq"] = 70
    assert _codes(_validate(tmp_path, patient, labels)) == {"seq_order"}


def test_detects_seq_not_in_recorded_order(tmp_path: Path) -> None:
    patient = _base_patient()
    _entry(patient, 1)["recorded_at"] = _at("2026-09-05", 21)  # seq2 より後
    assert _codes(_validate(tmp_path, patient, _base_labels())) == {"seq_order"}


def test_folfox_answer_types_match_skill_md() -> None:
    skills = pytest.importorskip("tsutae.skills")
    skill = skills.load_regimen_skill("FOLFOX")
    if skill.skill_version != synthetic.EXPECTED_SKILL_VERSION:
        pytest.skip(f"SKILL.md が {skill.skill_version}（合成データは @1）")
    expected = {q.key: q.answer_type for q in skill.questions}
    assert expected == synthetic.FOLFOX_ANSWER_TYPES


# ---------------------------------------------------------------------------
# 用語と question_key の対応
# ---------------------------------------------------------------------------


def test_term_question_keys_from_terms() -> None:
    mapping = synthetic.term_question_keys(synthetic.load_terms())
    assert mapping["下痢"] == "diarrhea"
    assert mapping["末梢神経障害"] == "numbness"
    assert mapping["倦怠感"] is None
    with pytest.raises(ValueError):
        synthetic.term_question_keys([{"term": "下痢", "question_key": 1}])


@pytest.mark.parametrize(
    ("term", "key", "expected"),
    [
        ("倦怠感", "fatigue", {"unknown_question_key", "term_question_key_mismatch"}),
        ("倦怠感", None, set()),
        # FOLFOX に手足症候群の質問は無いので question_key は None
        ("手足症候群", None, set()),
        (
            "手足症候群",
            "hand_foot",
            {"unknown_question_key", "term_question_key_mismatch"},
        ),
    ],
)
def test_event_question_key_outside_folfox(
    tmp_path: Path, term: str, key: str | None, expected: set[str]
) -> None:
    patient, labels = _base_patient(), _base_labels()
    _entry(patient, 7)["free_text"] = "しびれは少し残るが軽い。手のひらが赤い。"
    _label(labels, 7)["events"].append(
        _event("2026-09-22", 8, 2, term, "present", "手のひらが赤い", key)
    )
    assert _codes(_validate(tmp_path, patient, labels)) == expected


# ---------------------------------------------------------------------------
# 引用は一次置換後の文で検査できる（mask 引数）
# ---------------------------------------------------------------------------


def test_quotes_are_checked_against_masked_text(tmp_path: Path) -> None:
    pair = _load_pair(tmp_path, _base_patient(), _base_labels())
    assert synthetic.validate_dataset([pair], mask=lambda t: t) == []
    issues = synthetic.validate_dataset(
        [pair], mask=lambda t: t.replace("しびれ", "○○")
    )
    assert _codes(issues) == {"source_quote_mismatch"}
    assert sorted(int(re.search(r"seq=(\d+)", i).group(1)) for i in issues) == [
        3,
        4,
        7,
    ]

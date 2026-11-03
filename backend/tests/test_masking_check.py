"""`check_text`（一次→二次）と、合成データ全体での受け入れテスト。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from tsutae.config import SYNTHETIC_DIR
from tsutae.masking import MaskCheck, check_text, detect_identifiers, mask_text
from tsutae.masking.detect import RULE_UNKNOWN_BEFORE_HONORIFIC
from tsutae.schemas import PatientLabels, SyntheticPatient

DATASETS = ("demo_patient", "eval_patient_a", "eval_patient_b")


def test_check_text_masks_then_detects() -> None:
    check = check_text("鈴木さんと磯鷲さんに会った")
    assert isinstance(check, MaskCheck)
    assert check.masked == "○○さんと磯鷲さんに会った"
    assert [d.rule for d in check.detections] == [RULE_UNKNOWN_BEFORE_HONORIFIC]
    assert check.masked[check.detections[0].start : check.detections[0].end] == (
        "磯鷲さん"
    )
    assert check.flagged is True
    assert check.reason == RULE_UNKNOWN_BEFORE_HONORIFIC
    assert check.counts["name"] == 1


def test_check_text_clean_record() -> None:
    check = check_text("となりの鈴木さんがりんごをむいてくれた。電話090-0000-0000")
    assert check.masked == "となりの○○さんがりんごをむいてくれた。電話[伏せ字]"
    assert check.detections == ()
    assert check.flagged is False
    assert check.reason is None


def test_check_text_matches_mask_then_detect() -> None:
    text = "架空中央病院の磯鷲先生。番号は1234567"
    check = check_text(text)
    masked = mask_text(text).masked
    assert check.masked == masked
    assert check.detections == tuple(detect_identifiers(masked))


def test_check_is_frozen() -> None:
    check = check_text("鈴木さん")
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.masked = "x"  # type: ignore[misc]


def test_check_text_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        check_text(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 合成データでの受け入れ（読むだけ。ファイルが無ければ skip）
# ---------------------------------------------------------------------------


def _load(name: str) -> tuple[SyntheticPatient, PatientLabels]:
    patient_path = SYNTHETIC_DIR / f"{name}.json"
    labels_path = SYNTHETIC_DIR / f"labels_{name}.json"
    if not (patient_path.exists() and labels_path.exists()):
        pytest.skip(f"{name} の合成データがまだ無い")
    patient = SyntheticPatient.model_validate(_read_json(patient_path))
    labels = PatientLabels.model_validate(_read_json(labels_path))
    return patient, labels


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", DATASETS)
def test_synthetic_detections_match_expect_unprocessed(name: str) -> None:
    patient, labels = _load(name)
    by_seq = {label.entry_seq: label for label in labels.labels}
    mismatches = []
    for entry in patient.entries:
        if not entry.free_text or entry.seq not in by_seq:
            continue
        check = check_text(entry.free_text)
        expected = by_seq[entry.seq].expect_unprocessed
        if check.flagged != expected:
            rules = [d.rule for d in check.detections]
            mismatches.append((entry.seq, expected, rules, check.masked))
    assert mismatches == []


@pytest.mark.parametrize("name", DATASETS)
def test_synthetic_quotes_are_in_masked_text(name: str) -> None:
    patient, labels = _load(name)
    texts = {e.seq: e.free_text for e in patient.entries if e.free_text}
    missing = []
    for label in labels.labels:
        if label.expect_unprocessed or label.entry_seq not in texts:
            continue
        masked = check_text(texts[label.entry_seq]).masked
        quotes = [ev.source_quote for ev in label.events]
        quotes += [c.free_text_quote for c in label.contradictions]
        missing += [(label.entry_seq, q) for q in quotes if q not in masked]
    assert missing == []


def test_demo_has_exactly_one_unprocessed_record() -> None:
    patient, labels = _load("demo_patient")
    flagged = [
        e.seq
        for e in patient.entries
        if e.free_text and check_text(e.free_text).flagged
    ]
    expected = [label.entry_seq for label in labels.labels if label.expect_unprocessed]
    assert len(flagged) == 1
    assert flagged == expected

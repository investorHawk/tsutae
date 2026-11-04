"""tsutae.eval.cache と tsutae.eval.hook_counts（tmp_path に書く。API は呼ばない）。

入力は実物の `prepare_input` で合成データから作る。症例は全て合成。
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tsutae.config import SKILLS_DIR, SYNTHETIC_DIR
from tsutae.dataset import to_courses, to_entries
from tsutae.eval import hook_counts, run
from tsutae.eval.cache import CoursePrediction, load_predictions, save_prediction
from tsutae.eval.hook_counts import HookCounter, HookCounts
from tsutae.pipeline.hooks import make_h1, make_h2
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL
from tsutae.schemas import PreparedInput, Timeline
from tsutae.skills import load_regimen_skill, load_report_skill
from tsutae.synthetic import load_patient

PATIENT_A = "P-EVAL0001"


def _prepared() -> PreparedInput:
    patient = load_patient(SYNTHETIC_DIR / "eval_patient_a.json")
    return prepare_input(
        courses=to_courses(patient),
        entries=to_entries(patient),
        regimen_skill=load_regimen_skill(patient.regimen, SKILLS_DIR),
        report_skill=load_report_skill(skills_dir=SKILLS_DIR),
        visit_date=run.course_visit_dates(patient)[0][1],  # 第1コースの最終日
    )


def _prediction(**kw: Any) -> CoursePrediction:
    prepared = _prepared()
    base: dict[str, Any] = dict(
        patient_id=PATIENT_A,
        course_no=prepared.input.schedule.course_no,
        visit_date=prepared.input.schedule.last_day_date,
        model="m",
        subagent_model="s",
        prepared=prepared,
        timeline=Timeline(),
        fallback=False,
    )
    return CoursePrediction(**{**base, **kw})


def _saved_json(tmp_path: Path, prediction: CoursePrediction) -> tuple[Path, dict]:
    path = save_prediction(tmp_path, prediction)
    return path, json.loads(path.read_text(encoding="utf-8"))


def _rewrite(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 保存と読み込み
# ---------------------------------------------------------------------------


def test_round_trip_keeps_hook_counts(tmp_path: Path) -> None:
    hooks = HookCounts(h1_blocks=1, h2_timeline_denies=2, h2_report_denies=3)
    _, data = _saved_json(tmp_path, _prediction(hooks=hooks))
    assert data["format_version"] == 2
    assert data["hooks"] == {
        "h1_blocks": 1,
        "h2_timeline_denies": 2,
        "h2_report_denies": 3,
    }
    [loaded] = load_predictions(tmp_path)
    assert loaded.hooks == hooks


def test_old_format_version_is_rejected(tmp_path: Path) -> None:
    path, data = _saved_json(tmp_path, _prediction())
    data["format_version"] = 1
    del data["hooks"]
    _rewrite(path, data)
    with pytest.raises(ValueError):
        load_predictions(tmp_path)


def _first_no(data: dict) -> str:
    return next(iter(data["prepared"]["masked_texts"]))


@pytest.mark.parametrize(
    "tamper",
    [
        # 入力に無い entry_no を entry_ids に足す（その記録のラベルが分母に入る）
        lambda d: d["prepared"]["entry_ids"].update({"999": 999}),
        # entry_ids から入力の記録を落とす
        lambda d: d["prepared"]["entry_ids"].pop(
            next(iter(d["prepared"]["entry_ids"]))
        ),
        # 2つの entry_no が同じ記録を指す
        lambda d: d["prepared"]["entry_ids"].update(
            {"1": d["prepared"]["entry_ids"]["2"]}
        ),
        # 伏せ字後の文を入力の masked_free_text と違う文にする
        lambda d: d["prepared"]["masked_texts"].update({_first_no(d): "別の文"}),
        # 入力に無い entry_no の文を足す
        lambda d: d["prepared"]["masked_texts"].update({"999": "入力外の文"}),
        # 送信対象外の記録が入力にもある
        lambda d: d["prepared"]["unprocessed"].append(
            {"entry_id": d["prepared"]["entry_ids"]["1"], "reason": "long_digits"}
        ),
        # input.entries の entry_no の重複
        lambda d: d["prepared"]["input"]["entries"].append(
            d["prepared"]["input"]["entries"][0]
        ),
    ],
)
def test_inconsistent_cached_input_is_rejected(tmp_path: Path, tamper) -> None:
    path, data = _saved_json(tmp_path, _prediction())
    tamper(data)
    _rewrite(path, data)
    with pytest.raises(ValueError):
        load_predictions(tmp_path)


def test_consistent_cached_input_loads(tmp_path: Path) -> None:
    prediction = _prediction()
    save_prediction(tmp_path, prediction)
    [loaded] = load_predictions(tmp_path)
    assert loaded.prepared == prediction.prepared


def test_course_no_must_match_prepared_schedule() -> None:
    with pytest.raises(ValueError, match="コース"):
        _prediction(course_no=2)  # 入力は第1コース


def test_visit_date_after_course_last_day_is_rejected() -> None:
    last = _prepared().input.schedule.last_day_date
    with pytest.raises(ValueError, match="基準日"):
        _prediction(visit_date=last + timedelta(days=1))


def test_visit_date_before_infusion_is_rejected() -> None:
    infusion = _prepared().input.schedule.infusion_date
    with pytest.raises(ValueError, match="基準日"):
        _prediction(visit_date=infusion - timedelta(days=1))


@pytest.mark.parametrize(
    "tamper",
    [
        # 第1コースの入力のまま course_no だけ 2 にする
        lambda d: d.update({"course_no": 2}),
        # 基準日を入力のコースの最終日より後にする
        lambda d: d.update({"visit_date": "2026-09-28"}),
    ],
)
def test_course_mismatch_in_saved_file_is_rejected(tmp_path: Path, tamper) -> None:
    path, data = _saved_json(tmp_path, _prediction())
    tamper(data)
    _rewrite(path, data)
    with pytest.raises(ValueError):
        load_predictions(tmp_path)


# ---------------------------------------------------------------------------
# Hook の回数
# ---------------------------------------------------------------------------


def test_counter_counts_h1_and_h2_by_tool() -> None:
    counter = HookCounter()
    counter.event("run_start")
    counter.event("hook_h1_block", hook_name="H1", decision="block:at_mark")
    counter.event("hook_h2_deny", hook_name="H2", tool_name=EMIT_TIMELINE_TOOL)
    counter.event("hook_h2_deny", hook_name="H2", tool_name=EMIT_TIMELINE_TOOL)
    counter.event("hook_h2_deny", hook_name="H2", tool_name=EMIT_REPORT_TOOL)
    counter.event("hook_h4_deny", hook_name="H4", tool_name="Bash")
    assert counter.counts() == HookCounts(
        h1_blocks=1, h2_timeline_denies=2, h2_report_denies=1
    )


def test_counter_names_match_pipeline() -> None:
    assert hook_counts.EMIT_TIMELINE_TOOL == EMIT_TIMELINE_TOOL


def test_counter_counts_real_h2_deny_on_fabricated_quote() -> None:
    prepared = _prepared()
    no, text = next(iter(prepared.masked_texts.items()))
    tool_input = {
        "events": [
            {
                "entry_no": no,
                "date": "2026-09-01",
                "day": 1,
                "course_no": 1,
                "term": "嘔吐",
                "status": "present",
                "source_quote": "夜中に二回もどした",  # 記載に無い引用
                "confidence": 0.5,
            }
        ],
        "contradictions": [],
    }
    assert "夜中に二回もどした" not in text
    counter = HookCounter()
    memory = MemoryLogger()
    for logger in (counter, memory):
        h2 = make_h2(prepared.masked_texts, logger)
        data = {"tool_name": EMIT_TIMELINE_TOOL, "tool_input": tool_input}
        out = asyncio.run(h2(data, "toolu_1", {}))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert counter.counts().h2_timeline_denies == 1
    assert memory.names() == ["hook_h2_deny"]  # 実物の event 名と同じものを数える


def test_counter_counts_real_h1_block() -> None:
    counter = HookCounter()
    h1 = make_h1(counter)
    out = asyncio.run(h1({"prompt": "連絡先 taro@example.com"}, None, {}))
    assert out["decision"] == "block"
    assert counter.counts().h1_blocks == 1


def test_hook_counts_add() -> None:
    total = HookCounts(h1_blocks=1, h2_timeline_denies=2) + HookCounts(
        h2_timeline_denies=1, h2_report_denies=4
    )
    assert total == HookCounts(h1_blocks=1, h2_timeline_denies=3, h2_report_denies=4)

"""tsutae.eval.run: 変換関数を差し込んだ通しと --cache-only（tmp_path に書く。API は呼ばない）。

入力は実物の `tsutae.pipeline.inputs.prepare_input` で作る。変換は差し込む偽物か、
実物の `convert` に台本どおりに動く FakeRunner（tests/pipeline_fakes.py）を渡す。
症例は全て合成。
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from pipeline_fakes import FakeRunner, Step, label_payloads

from tsutae import config
from tsutae.config import JST, SYNTHETIC_DIR
from tsutae.eval import run
from tsutae.eval.hook_counts import HookCounter
from tsutae.masking import check_text
from tsutae.pipeline import runner as pipeline_runner
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL
from tsutae.schemas import (
    Contradiction,
    ConversionResult,
    PatientLabels,
    PreparedInput,
    RunStats,
    Timeline,
    TimelineEvent,
)
from tsutae.synthetic import load_labels, load_patient

PATIENT_A = "P-EVAL0001"
PATIENT_B = "P-EVAL0002"


# ---------------------------------------------------------------------------
# 偽の変換
# ---------------------------------------------------------------------------


STATS = RunStats(
    duration_ms=1500, num_turns=3, tokens_in=100, tokens_out=50, cost_usd=0.0125
)


def perfect_timeline(labels: PatientLabels, prepared: PreparedInput) -> Timeline:
    """正解ラベルをそのまま予測にした Timeline（今回の入力の記録だけ）。"""
    by_seq = {label.entry_seq: label for label in labels.labels}
    entries = {e.entry_no: e for e in prepared.input.entries}
    events: list[TimelineEvent] = []
    contradictions: list[Contradiction] = []
    for no, seq in prepared.entry_ids.items():
        label = by_seq.get(seq)
        if label is None or label.expect_unprocessed:
            continue
        events += [
            TimelineEvent(entry_no=no, confidence=1.0, **ev.model_dump())
            for ev in label.events
        ]
        contradictions += [
            Contradiction(
                entry_no=no,
                date=entries[no].record_date,
                day=entries[no].day,
                **c.model_dump(),
            )
            for c in label.contradictions
        ]
    return Timeline(
        events=events,
        contradictions=contradictions,
        unprocessed_entries=list(prepared.unprocessed),
    )


def perfect_convert(labels: PatientLabels):
    """正解ラベルをそのまま予測として返す（1患者分）。"""

    def _convert(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
        return ConversionResult(
            timeline=perfect_timeline(labels, prepared),
            picks=None,
            fallback=False,
            stats=STATS,
        )

    return _convert


def empty_convert(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
    return ConversionResult(timeline=Timeline(), picks=None, fallback=False)


def _labels(name: str) -> PatientLabels:
    return load_labels(SYNTHETIC_DIR / f"labels_{name}.json")


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "runs", tmp_path / "out"


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    runs, out = _dirs(tmp_path)
    return ["--runs-dir", str(runs), "--out-dir", str(out), *extra]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")
    monkeypatch.setenv("TSUTAE_MODEL", "test-main-model")
    monkeypatch.setenv("TSUTAE_SUBAGENT_MODEL", "test-sub-model")


def _only_run_dir(tmp_path: Path) -> Path:
    runs, _ = _dirs(tmp_path)
    [run_dir] = list(runs.iterdir())
    return run_dir


# ---------------------------------------------------------------------------
# コースと受診日
# ---------------------------------------------------------------------------


def test_course_visit_dates_use_day_before_next_course() -> None:
    patient = load_patient(SYNTHETIC_DIR / "eval_patient_b.json")
    assert run.course_visit_dates(patient) == [
        (1, date(2026, 9, 7)),  # 次コース実投与 09-08 の前日（延期で Day21）
        (2, date(2026, 9, 21)),  # 最後のコースは patient.visit_date
    ]


def test_eval_cases_pick_eval_patients_only() -> None:
    cases = run.eval_cases(SYNTHETIC_DIR)
    assert [(c.patient.patient_id, c.course_no) for c in cases] == [
        (PATIENT_A, 1),
        (PATIENT_A, 2),
        (PATIENT_B, 1),
        (PATIENT_B, 2),
    ]


def test_eval_cases_filter_by_id_or_file_name() -> None:
    by_id = run.eval_cases(SYNTHETIC_DIR, [PATIENT_B])
    by_name = run.eval_cases(SYNTHETIC_DIR, ["eval_patient_b"])
    assert {c.patient.patient_id for c in by_id} == {PATIENT_B}
    assert [c.course_no for c in by_name] == [1, 2]


@pytest.mark.parametrize("wanted", [["P-NOBODY00"], ["demo_patient"], ["P-DEMO0001"]])
def test_eval_cases_reject_unknown_or_demo_patient(wanted: list[str]) -> None:
    with pytest.raises(ValueError):
        run.eval_cases(SYNTHETIC_DIR, wanted)


def test_new_run_dir_avoids_collision(tmp_path: Path) -> None:
    at = datetime(2026, 11, 6, 15, 30, tzinfo=JST)
    first = run.new_run_dir(tmp_path, at)
    second = run.new_run_dir(tmp_path, at)
    assert first.name == "20261106-1530"
    assert second.name == "20261106-1530-2"
    assert first.is_dir() and second.is_dir()


# ---------------------------------------------------------------------------
# 通し（変換関数を差し込む）
# ---------------------------------------------------------------------------


def test_full_run_with_perfect_convert(tmp_path: Path) -> None:
    code = run.main(
        _argv(tmp_path, "--patients", PATIENT_A),
        prepare_fn=prepare_input,
        convert_fn=perfect_convert(_labels("eval_patient_a")),
    )
    assert code == 0
    run_dir = _only_run_dir(tmp_path)
    assert run_dir.name.startswith("20261109-")
    files = sorted(p.name for p in run_dir.iterdir())
    assert files == [f"{PATIENT_A}_c1.json", f"{PATIENT_A}_c2.json"]

    saved = json.loads((run_dir / f"{PATIENT_A}_c1.json").read_text(encoding="utf-8"))
    assert saved["patient_id"] == PATIENT_A and saved["course_no"] == 1
    assert saved["visit_date"] == "2026-09-14"
    assert saved["model"] == "test-main-model"
    assert saved["stats"]["cost_usd"] == pytest.approx(0.0125)
    assert saved["error_code"] is None and saved["timeline"]["events"]

    _, out = _dirs(tmp_path)
    md = (out / "2026-11-09.md").read_text(encoding="utf-8")
    assert "症例は全て合成" in md
    assert "合格ラインは置かず実測値と失敗例を出す" in md
    assert "test-main-model" in md and "test-sub-model" in md
    assert "100.0%" in md
    assert "失敗例（0件）" in md
    assert f"| {PATIENT_A} | 1 |" in md and f"| {PATIENT_A} | 2 |" in md
    assert "$0.0250" in md  # 2コース分の費用
    assert "3.0 秒" in md  # 変換の所要時間（1.5 秒 × 2）


def test_saved_predictions_hold_no_raw_text(tmp_path: Path) -> None:
    run.main(
        _argv(tmp_path),
        prepare_fn=prepare_input,
        convert_fn=empty_convert,
    )
    text = "".join(
        p.read_text(encoding="utf-8") for p in _only_run_dir(tmp_path).iterdir()
    )
    raw_only = []
    for name in ("eval_patient_a", "eval_patient_b"):
        patient = load_patient(SYNTHETIC_DIR / f"{name}.json")
        assert patient.reception_no not in text
        raw_only += [
            e.free_text
            for e in patient.entries
            if e.free_text and check_text(e.free_text).masked != e.free_text
        ]
    assert raw_only  # 一次置換が効く記載が評価データにある
    assert "田中" not in text and "090-0000-0000" not in text
    assert all(raw not in text for raw in raw_only)
    assert "○○さん" in text  # 伏せ字後の文は入る


def test_run_covers_every_eval_course(tmp_path: Path) -> None:
    seen: list[int] = []

    def _record(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
        seen.append(prepared.input.schedule.course_no)
        return ConversionResult(timeline=Timeline(), picks=None, fallback=False)

    assert run.main(_argv(tmp_path), prepare_fn=prepare_input, convert_fn=_record) == 0
    assert seen == [1, 2, 1, 2]
    names = sorted(p.name for p in _only_run_dir(tmp_path).iterdir())
    assert names == [
        f"{PATIENT_A}_c1.json",
        f"{PATIENT_A}_c2.json",
        f"{PATIENT_B}_c1.json",
        f"{PATIENT_B}_c2.json",
    ]


def _md(tmp_path: Path) -> str:
    _, out = _dirs(tmp_path)
    return (out / "2026-11-09.md").read_text(encoding="utf-8")


def test_some_exceptions_are_recorded_and_exit_non_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def _flaky(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
        if prepared.input.schedule.course_no == 1:
            raise RuntimeError("boom")
        return ConversionResult(
            timeline=None, picks=None, fallback=True, error_code="timeout"
        )

    code = run.main(
        _argv(tmp_path, "--patients", PATIENT_A),
        prepare_fn=prepare_input,
        convert_fn=_flaky,
    )
    assert code == 3
    run_dir = _only_run_dir(tmp_path)
    c1 = json.loads((run_dir / f"{PATIENT_A}_c1.json").read_text(encoding="utf-8"))
    c2 = json.loads((run_dir / f"{PATIENT_A}_c2.json").read_text(encoding="utf-8"))
    assert c1["error_code"] == "eval_exception" and c1["timeline"] is None
    assert c2["error_code"] == "timeout" and c2["fallback"] is True
    md = _md(tmp_path)
    assert "AI変換なし（timeout）" in md
    assert "AI変換なし（eval_exception）" in md
    head = md.split("## 5指標")[0]
    assert "変換で想定外の例外が出たコース 1 件" in head
    captured = capsys.readouterr()
    assert "boom" not in md
    assert "boom" not in captured.err and "boom" not in captured.out
    assert "RuntimeError" in captured.err


def test_all_courses_exception_writes_no_md(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def _broken(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
        raise RuntimeError("boom")

    code = run.main(_argv(tmp_path), prepare_fn=prepare_input, convert_fn=_broken)
    assert code == 3
    _, out = _dirs(tmp_path)
    assert not out.exists() or not list(out.glob("*.md"))
    assert len(list(_only_run_dir(tmp_path).iterdir())) == 4  # 予測は残す
    captured = capsys.readouterr()
    assert "boom" not in captured.err and "boom" not in captured.out


def test_internal_error_of_convert_counts_as_unexpected(tmp_path: Path) -> None:
    def _internal(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
        return ConversionResult(
            timeline=None, picks=None, fallback=True, error_code="internal_error"
        )

    code = run.main(_argv(tmp_path), prepare_fn=prepare_input, convert_fn=_internal)
    assert code == 3
    _, out = _dirs(tmp_path)
    assert not out.exists() or not list(out.glob("*.md"))


@pytest.mark.parametrize("error", [TypeError, AttributeError, NameError])
def test_programming_error_in_convert_is_not_swallowed(
    tmp_path: Path, error: type[Exception]
) -> None:
    # convert の呼び方・SdkRunner の作り方が契約とずれたとき（0% の md を残さない）
    def _wrong_contract(prepared: PreparedInput, logger: HookCounter):
        raise error("contract mismatch")

    with pytest.raises(error):
        run.main(_argv(tmp_path), prepare_fn=prepare_input, convert_fn=_wrong_contract)
    _, out = _dirs(tmp_path)
    assert not out.exists() or not list(out.glob("*.md"))


def test_convert_returning_wrong_type_is_a_type_error(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        run.main(
            _argv(tmp_path, "--patients", PATIENT_A),
            prepare_fn=prepare_input,
            convert_fn=lambda prepared, logger: Timeline(),
        )


def test_hook_counts_are_saved_and_shown(tmp_path: Path) -> None:
    good = perfect_convert(_labels("eval_patient_a"))

    def _with_denies(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
        logger.event("hook_h2_deny", hook_name="H2", tool_name=EMIT_TIMELINE_TOOL)
        logger.event("hook_h2_deny", hook_name="H2", tool_name=EMIT_TIMELINE_TOOL)
        return good(prepared, logger)

    code = run.main(
        _argv(tmp_path, "--patients", PATIENT_A),
        prepare_fn=prepare_input,
        convert_fn=_with_denies,
    )
    assert code == 0
    saved = json.loads(
        (_only_run_dir(tmp_path) / f"{PATIENT_A}_c1.json").read_text(encoding="utf-8")
    )
    assert saved["format_version"] == 2
    assert saved["hooks"]["h2_timeline_denies"] == 2
    md = _md(tmp_path)
    assert "H2 が拒否した引用: emit_timeline 4 回" in md  # 2コース × 2回
    assert "構造上 100%" in md


# ---------------------------------------------------------------------------
# 実物の prepare_input と convert（FakeRunner。API は呼ばない）
# ---------------------------------------------------------------------------


def _label_event_total(name: str) -> int:
    return sum(
        len(label.events)
        for label in _labels(name).labels
        if not label.expect_unprocessed
    )


@pytest.mark.parametrize(
    ("name", "patient_id", "expected"),
    [("eval_patient_a", PATIENT_A, 29), ("eval_patient_b", PATIENT_B, 32)],
)
def test_real_prepare_input_covers_every_label(
    name: str, patient_id: str, expected: int
) -> None:
    labels = _labels(name)
    predictions = [
        run.predict_case(
            case,
            prepare_fn=prepare_input,
            convert_fn=perfect_convert(labels),
            model="m",
            subagent_model="s",
        )
        for case in run.eval_cases(SYNTHETIC_DIR, [patient_id])
    ]
    assert [p.prepared.unprocessed for p in predictions] == [[], []]
    scores = run.score_predictions(predictions, {patient_id: labels})
    total = sum(s.result.label_events for s in scores)
    assert total == expected == _label_event_total(name)
    assert all(s.result.held_out_label_events == 0 for s in scores)
    assert all(s.result.failures == [] for s in scores)


def test_default_convert_runs_real_convert_and_counts_h2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 実物の convert・Hook に、台本どおりに動く FakeRunner を渡す（SdkRunner の代わり）。
    # 1回目の emit_timeline は捏造した引用で H2 が拒否し、2回目は正解を出す
    seen: list[PreparedInput] = []
    runners: list[FakeRunner] = []

    def _prepare(**kwargs) -> PreparedInput:
        prepared = prepare_input(**kwargs)
        seen.append(prepared)
        return prepared

    def _sdk_runner() -> FakeRunner:
        # 正解ラベルから作った emit_timeline / emit_report の入力（両方が要る）
        good, report = label_payloads("eval_patient_a", seen[-1])
        bad = copy.deepcopy(good)
        bad["events"][0]["source_quote"] = "夜中に二回もどした"
        runner = FakeRunner(
            [
                Step(EMIT_TIMELINE_TOOL, bad),
                Step(EMIT_TIMELINE_TOOL, good),
                Step(EMIT_REPORT_TOOL, report),  # convert は report も要る
            ]
        )
        runners.append(runner)
        return runner

    monkeypatch.setattr(pipeline_runner, "SdkRunner", _sdk_runner)
    convert_fn = run.default_convert_fn(config.get_settings())
    code = run.main(
        _argv(tmp_path, "--patients", PATIENT_A),
        prepare_fn=_prepare,
        convert_fn=convert_fn,
    )
    assert code == 0
    assert len(runners) == 2 and all(len(r.denied()) == 1 for r in runners)
    saved = json.loads(
        (_only_run_dir(tmp_path) / f"{PATIENT_A}_c1.json").read_text(encoding="utf-8")
    )
    assert saved["hooks"]["h2_timeline_denies"] == 1
    assert saved["error_code"] is None and saved["timeline"]["events"]
    md = _md(tmp_path)
    assert "H2 が拒否した引用: emit_timeline 2 回" in md
    assert "失敗例（0件）" in md


def test_sdk_runner_can_be_built_without_arguments() -> None:
    # default_convert_fn は SdkRunner() を引数なしで作る（作るだけ。API は呼ばない）
    assert isinstance(pipeline_runner.SdkRunner(), pipeline_runner.AgentRunner)


def test_prepare_for_wrong_course_is_an_error(tmp_path: Path) -> None:
    def _always_course_2(**kwargs) -> PreparedInput:
        kwargs["visit_date"] = date(2026, 9, 28)
        return prepare_input(**kwargs)

    code = run.main(
        _argv(tmp_path, "--patients", PATIENT_A),
        prepare_fn=_always_course_2,
        convert_fn=perfect_convert(_labels("eval_patient_a")),
    )
    assert code == 2


# ---------------------------------------------------------------------------
# --cache-only
# ---------------------------------------------------------------------------


def _boom(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
    raise AssertionError("--cache-only で変換を呼んではいけない")


def test_cache_only_recomputes_without_converting(tmp_path: Path) -> None:
    run.main(
        _argv(tmp_path, "--patients", PATIENT_A),
        prepare_fn=prepare_input,
        convert_fn=perfect_convert(_labels("eval_patient_a")),
    )
    run_dir = _only_run_dir(tmp_path)
    code = run.main(
        _argv(tmp_path, "--cache-only", str(run_dir)),
        prepare_fn=prepare_input,  # 入力の照合に作り直す（純関数。API は呼ばない）
        convert_fn=_boom,
    )
    assert code == 0
    _, out = _dirs(tmp_path)
    first = (out / "2026-11-09.md").read_text(encoding="utf-8")
    second = (out / "2026-11-09-2.md").read_text(encoding="utf-8")
    assert "保存済みの予測から再計算" in second
    section = first.split("## 5指標")[1]
    assert second.split("## 5指標")[1] == section
    assert "test-main-model" in second


def test_cache_only_from_hand_made_run_dir_lists_failures(tmp_path: Path) -> None:
    patient = load_patient(SYNTHETIC_DIR / "eval_patient_a.json")
    labels = _labels("eval_patient_a")
    case = next(
        c for c in run.eval_cases(SYNTHETIC_DIR, [PATIENT_A]) if c.course_no == 1
    )
    good = perfect_convert(labels)
    fabricated = TimelineEvent(
        entry_no=1,
        date=date(2026, 9, 1),
        day=1,
        course_no=1,
        term="嘔吐",
        status="present",
        source_quote="夜中に二回もどした",
        confidence=0.4,
    )

    def _with_fabrication(
        prepared: PreparedInput, logger: HookCounter
    ) -> ConversionResult:
        result = good(prepared, logger)
        assert result.timeline is not None
        timeline = result.timeline.model_copy(
            update={"events": [*result.timeline.events, fabricated]}
        )
        return result.model_copy(update={"timeline": timeline})

    prediction = run.predict_case(
        case,
        prepare_fn=prepare_input,
        convert_fn=_with_fabrication,
        model="hand-model",
        subagent_model="hand-sub",
    )
    run_dir = tmp_path / "runs" / "handmade"
    run_dir.mkdir(parents=True)
    run.save_prediction(run_dir, prediction)
    assert patient.patient_id == PATIENT_A

    code = run.main(_argv(tmp_path, "--cache-only", str(run_dir)), convert_fn=_boom)
    assert code == 0
    _, out = _dirs(tmp_path)
    md = (out / "2026-11-09.md").read_text(encoding="utf-8")
    assert "夜中に二回もどした" in md  # H2 を通らない手作りの予測なら引用の失敗に出る
    assert "| 引用 |" in md
    assert "hand-model" in md
    assert "失敗例（1件）" in md


def _saved_run(tmp_path: Path, patient_id: str = PATIENT_A) -> Path:
    """perfect_convert の予測を tmp_path/runs/saved に保存する（全コース）。"""
    name = "eval_patient_a" if patient_id == PATIENT_A else "eval_patient_b"
    run_dir = tmp_path / "runs" / "saved"
    run_dir.mkdir(parents=True, exist_ok=True)
    for case in run.eval_cases(SYNTHETIC_DIR, [patient_id]):
        prediction = run.predict_case(
            case,
            prepare_fn=prepare_input,
            convert_fn=perfect_convert(_labels(name)),
            model="m",
            subagent_model="s",
        )
        run.save_prediction(run_dir, prediction)
    return run_dir


def _drop_entry(data: dict, seq: int) -> None:
    """記録 seq を entry_ids・masked_texts・input.entries から辻褄を合わせて消す。"""
    prepared = data["prepared"]
    [no] = [k for k, v in prepared["entry_ids"].items() if v == seq]
    del prepared["entry_ids"][no]
    prepared["masked_texts"].pop(no, None)
    entries = prepared["input"]["entries"]
    prepared["input"]["entries"] = [e for e in entries if str(e["entry_no"]) != no]


def _no_md(tmp_path: Path) -> bool:
    _, out = _dirs(tmp_path)
    return not out.exists() or not list(out.glob("*.md"))


def test_cache_only_rejects_consistently_dropped_entry(tmp_path: Path) -> None:
    # 辻褄を合わせて記録を消すと、ファイルの中の検査は通る（分母が 15 → 12 に減る）。
    # 合成データから作り直した入力と比べて拒否する
    run_dir = _saved_run(tmp_path)
    path = run_dir / f"{PATIENT_A}_c1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    _drop_entry(data, 2)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    loaded = run.load_predictions(run_dir)  # ファイルの中だけなら辻褄は合っている
    labels = {PATIENT_A: _labels("eval_patient_a")}
    [c1, _] = run.score_predictions(loaded, labels)
    assert c1.result.label_events == 12
    code = run.main(_argv(tmp_path, "--cache-only", str(run_dir)), convert_fn=_boom)
    assert code == 2
    assert _no_md(tmp_path)


def test_cache_only_rejects_swapped_patient(tmp_path: Path) -> None:
    # A の患者IDに B の入力（第1コース、基準日も B に合わせる）
    run_dir = _saved_run(tmp_path, PATIENT_B)
    for path in list(run_dir.iterdir()):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["patient_id"] = PATIENT_A
        path.unlink()
        (run_dir / f"{PATIENT_A}_c{data['course_no']}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    assert len(run.load_predictions(run_dir)) == 2
    code = run.main(_argv(tmp_path, "--cache-only", str(run_dir)), convert_fn=_boom)
    assert code == 2
    assert _no_md(tmp_path)


def test_cache_only_rejects_unknown_course(tmp_path: Path) -> None:
    run_dir = _saved_run(tmp_path)
    c2 = run_dir / f"{PATIENT_A}_c2.json"
    data = json.loads(c2.read_text(encoding="utf-8"))
    data["prepared"]["input"]["schedule"]["course_no"] = 3
    data["course_no"] = 3
    c2.unlink()
    (run_dir / f"{PATIENT_A}_c3.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    code = run.main(_argv(tmp_path, "--cache-only", str(run_dir)), convert_fn=_boom)
    assert code == 2


def test_cache_only_untouched_files_keep_full_denominator(tmp_path: Path) -> None:
    run_dir = _saved_run(tmp_path)
    code = run.main(_argv(tmp_path, "--cache-only", str(run_dir)), convert_fn=_boom)
    assert code == 0
    md = _md(tmp_path)
    assert "全 29 件 = 数えた 29 件 + 二次検出で外れた 0 件 + 入力外 0 件" in md


def test_cache_only_missing_course_file_shows_outside_events(tmp_path: Path) -> None:
    # コースのファイルごと消すと読み込みは通るが、入力外の出来事として md に残る
    run_dir = _saved_run(tmp_path)
    (run_dir / f"{PATIENT_A}_c2.json").unlink()
    code = run.main(_argv(tmp_path, "--cache-only", str(run_dir)), convert_fn=_boom)
    assert code == 0
    head = _md(tmp_path).split("## 5指標")[0]
    assert "全 29 件 = 数えた 15 件 + 二次検出で外れた 0 件 + 入力外 14 件" in head
    assert "正解ラベルの出来事 14 件が今回の入力に入っていない" in head


def test_cache_only_outside_out_dir_does_not_write_local_path(tmp_path: Path) -> None:
    run_dir = _saved_run(tmp_path / "elsewhere")
    code = run.main(_argv(tmp_path, "--cache-only", str(run_dir)), convert_fn=_boom)
    assert code == 0
    md = _md(tmp_path)
    assert str(tmp_path) not in md and str(tmp_path.resolve()) not in md
    label_line = next(line for line in md.splitlines() if line.startswith("- 予測:"))
    assert "saved" in label_line


def test_cache_only_missing_dir_is_an_error(tmp_path: Path) -> None:
    code = run.main(_argv(tmp_path, "--cache-only", str(tmp_path / "nothing")))
    assert code == 2


def test_cache_only_rejects_broken_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "broken"
    run_dir.mkdir(parents=True)
    (run_dir / f"{PATIENT_A}_c1.json").write_text("{not json", encoding="utf-8")
    assert run.main(_argv(tmp_path, "--cache-only", str(run_dir))) == 2


def test_unknown_patient_is_an_error(tmp_path: Path) -> None:
    code = run.main(
        _argv(tmp_path, "--patients", "P-NOBODY00"),
        prepare_fn=prepare_input,
        convert_fn=_boom,
    )
    assert code == 2


def test_save_prediction_drops_texts_outside_input(tmp_path: Path) -> None:
    case = run.eval_cases(SYNTHETIC_DIR, [PATIENT_A])[0]
    prediction = run.predict_case(
        case,
        prepare_fn=prepare_input,
        convert_fn=empty_convert,
        model="m",
        subagent_model="s",
    )
    leaked = prediction.prepared.model_copy(
        update={"masked_texts": {**prediction.prepared.masked_texts, 999: "入力外の文"}}
    )
    path = run.save_prediction(
        tmp_path, prediction.model_copy(update={"prepared": leaked})
    )
    assert "入力外の文" not in path.read_text(encoding="utf-8")
    [loaded] = run.load_predictions(tmp_path)
    assert 999 not in loaded.prepared.masked_texts


PIPELINE_MODULES = (
    "tsutae.pipeline",
    "tsutae.pipeline.inputs",
    "tsutae.pipeline.logs",
    "tsutae.pipeline.orchestrator",
    "tsutae.pipeline.runner",
)


def test_missing_pipeline_stops_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 既定の変換（API を呼ぶ）が絶対に動かないよう、pipeline の import を全て止める
    for name in PIPELINE_MODULES:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setattr(config, "load_env_file", lambda *a, **k: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")  # キーの関所は通す
    code = run.main(_argv(tmp_path, "--patients", PATIENT_A), prepare_fn=prepare_input)
    assert code == 2
    runs, out = _dirs(tmp_path)
    assert not runs.exists() and not out.exists()


def test_missing_api_key_stops_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 既定の変換を作る前に止まる（pipeline の import も止めて二重に守る）
    for name in PIPELINE_MODULES:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setattr(config, "load_env_file", lambda *a, **k: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = run.main(_argv(tmp_path, "--patients", PATIENT_A), prepare_fn=prepare_input)
    assert code == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    runs, out = _dirs(tmp_path)
    assert not runs.exists() and not out.exists()

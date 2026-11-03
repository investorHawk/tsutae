"""受診時の生成（tsutae.pipeline.service）。docs/architecture.md §7d。

DB は tmp_path。デモ患者を tsutae.dataset で入れ、runner は FakeRunner（API は呼ばない）。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from pipeline_fakes import (
    FakeRunner,
    RaisingRunner,
    SlowRunner,
    label_payloads,
    standard_steps,
)

from tsutae import db
from tsutae.config import SKILLS_DIR, SYNTHETIC_DIR, get_settings, jst_datetime
from tsutae.dataset import to_courses, to_entry_create
from tsutae.pipeline import MemoryLogger, prepare_input, service
from tsutae.pipeline.service import (
    ensure_skill_versions,
    generate_visit_report,
    questions_by_version,
)
from tsutae.pipeline.tools import RunCollector
from tsutae.schemas import ClosedAnswer, EntryCreate, PreparedInput, RunStats
from tsutae.skills import load_regimen_skill, load_report_skill
from tsutae.synthetic import load_patient

DEMO = load_patient(SYNTHETIC_DIR / "demo_patient.json")
PID = DEMO.patient_id
RECEPTION_NO = DEMO.reception_no
UNPROCESSED_SEQ = 38  # 「磯鷲さん」（辞書にない架空の姓＋さん。二次検出）
UNPROCESSED_WORD = "磯鷲"


@pytest.fixture
def conn(tmp_db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_db_path)
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def settings(tmp_db_path: Path) -> Any:
    return replace(get_settings(), db_path=tmp_db_path, skills_dir=SKILLS_DIR)


def _seed_demo(conn: sqlite3.Connection) -> None:
    db.create_patient(conn, DEMO.regimen, patient_id=PID)
    for course in to_courses(DEMO):
        db.upsert_course(conn, course)
    for src in DEMO.entries:
        saved = db.add_entry(
            conn, PID, to_entry_create(src), src.recorded_at, src.skill_version
        )
        assert saved.id == src.seq  # 正解ラベル（entry_seq）と突き合わせる前提
    ensure_skill_versions(conn, SKILLS_DIR)


def _visit(conn: sqlite3.Connection, reception_no: str = RECEPTION_NO) -> int:
    return db.create_visit(
        conn,
        PID,
        reception_no,
        DEMO.visit_date,
        jst_datetime(date(2026, 11, 10), 12),
        3,
    )


@pytest.fixture
def demo(conn: sqlite3.Connection) -> int:
    _seed_demo(conn)
    return _visit(conn)


def _prepared(conn: sqlite3.Connection) -> PreparedInput:
    """service と同じ入力（DB から作り直す。id のズレに気づけるように）。"""
    return prepare_input(
        courses=db.list_courses(conn, PID),
        entries=db.list_entries(conn, PID),
        regimen_skill=load_regimen_skill("FOLFOX", SKILLS_DIR),
        report_skill=load_report_skill(skills_dir=SKILLS_DIR),
        visit_date=DEMO.visit_date,
        exclude_literals=(PID, RECEPTION_NO),
    )


def _label_runner(conn: sqlite3.Connection) -> FakeRunner:
    timeline, report = label_payloads("demo_patient", _prepared(conn))
    return FakeRunner(standard_steps(timeline, report))


def _add_entry(conn: sqlite3.Connection, text: str, at: datetime) -> int:
    entry = db.add_entry(conn, PID, EntryCreate(free_text=text), at, "regimen-folfox@1")
    return entry.id


def _raiser(exc: BaseException) -> Callable[..., Any]:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return broken


def _events(conn: sqlite3.Connection, vid: int) -> list[str]:
    return [r["event"] for r in db.list_pipeline_logs(conn, "visit", vid)]


# ---------------------------------------------------------------------------
# 正常
# ---------------------------------------------------------------------------


async def test_ready_with_attention_items(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    runner = _label_runner(conn)
    await generate_visit_report(conn, demo, runner=runner, settings=settings)

    assert runner.calls == 1
    assert runner.denied() == []
    visit = db.get_visit(conn, demo)
    assert visit["status"] == "ready"
    assert visit["fallback"] is False
    html, data = db.get_report(conn, demo)
    kinds = {a.kind for a in data.attention}
    assert {"contradiction", "fever", "too_sick", "unprocessed"} <= kinds
    assert "要確認" in html
    assert "食い違い" in html
    assert "発熱" in html
    assert "37.9" in html
    assert "つらくて書けない" in html
    assert "未処理の記載あり" in html
    assert "AI変換なし" not in html
    assert data.per_symptom  # AI の結果（症状別の時系列）が載る
    timeline = db.get_timeline(conn, demo)
    assert timeline is not None and timeline.events


async def test_logs_run_start_and_end_without_text(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    await generate_visit_report(
        conn, demo, runner=_label_runner(conn), settings=settings
    )
    logs = db.list_pipeline_logs(conn, "visit", demo)
    names = [r["event"] for r in logs]
    assert names.count("run_start") == 1
    assert names.count("run_end") == 1
    assert "fallback" not in names
    for row in logs:
        for value in row.values():
            if isinstance(value, str):
                assert value.isascii()  # 文面（日本語）を入れない
                assert RECEPTION_NO not in value  # 受付番号・仮名IDも入れない
                assert PID.casefold() not in value.casefold()


async def test_uses_given_logger(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    logger = MemoryLogger()
    await generate_visit_report(
        conn, demo, runner=_label_runner(conn), settings=settings, logger=logger
    )
    assert "run_start" in logger.names()
    assert "run_end" in logger.names()
    assert _events(conn, demo) == []


# ---------------------------------------------------------------------------
# 識別子を Claude に送らない
# ---------------------------------------------------------------------------


async def test_prompt_has_no_reception_no_or_patient_id(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    runner = _label_runner(conn)
    await generate_visit_report(conn, demo, runner=runner, settings=settings)
    prompt = runner.prompts[0]
    assert RECEPTION_NO not in prompt
    assert PID not in prompt
    assert PID.casefold() not in prompt.casefold()
    assert UNPROCESSED_WORD not in prompt
    system = str(runner.options.system_prompt) if runner.options else ""
    assert RECEPTION_NO not in system and PID not in system


@pytest.mark.parametrize(
    "text",
    [
        f"受付番号は{RECEPTION_NO}と言われた。下痢はなかった",
        "受付番号はＡ－０２３と言われた",  # 全角（NFKC で同じ）
        f"自分のIDは{PID}だった",  # 一次で [ID] になる前の原文で比べる
        f"自分のIDは{PID.lower()}だった",
    ],
)
async def test_free_text_with_known_identifier_is_unprocessed(
    conn: sqlite3.Connection, settings: Any, text: str
) -> None:
    _seed_demo(conn)
    entry_id = _add_entry(conn, text, jst_datetime(date(2026, 11, 8), 22))
    vid = _visit(conn)
    runner = FakeRunner()  # 何も出さない → フォールバック
    await generate_visit_report(conn, vid, runner=runner, settings=settings)

    timeline = db.get_timeline(conn, vid)
    reasons = {u.entry_id: u.reason for u in timeline.unprocessed_entries}
    assert reasons[entry_id] == "known_identifier"
    prompt = runner.prompts[0]
    assert RECEPTION_NO not in prompt and "０２３" not in prompt
    assert PID.casefold() not in prompt.casefold()
    html, _data = db.get_report(conn, vid)
    assert "受付番号は" not in html and "自分のID" not in html


async def test_secondary_detection_is_saved_as_unprocessed(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    await generate_visit_report(
        conn, demo, runner=_label_runner(conn), settings=settings
    )
    timeline = db.get_timeline(conn, demo)
    reasons = {u.entry_id: u.reason for u in timeline.unprocessed_entries}
    assert reasons == {UNPROCESSED_SEQ: "unknown_before_honorific"}
    html, data = db.get_report(conn, demo)
    assert UNPROCESSED_WORD not in html
    assert UNPROCESSED_WORD not in data.model_dump_json()
    unprocessed = [a for a in data.attention if a.kind == "unprocessed"]
    assert [a.count for a in unprocessed] == [1]


# ---------------------------------------------------------------------------
# フォールバック・失敗
# ---------------------------------------------------------------------------


async def test_runner_exception_gives_fallback_ready(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    runner = RaisingRunner(RuntimeError("患者の文を含むかもしれない本文"))
    await generate_visit_report(conn, demo, runner=runner, settings=settings)

    assert runner.calls == 1
    visit = db.get_visit(conn, demo)
    assert visit["status"] == "ready"
    assert visit["fallback"] is True
    html, data = db.get_report(conn, demo)
    assert data.fallback is True
    assert "AI変換なし" in html
    assert "発熱" in html  # 記録からコードで決まる要確認は出る
    timeline = db.get_timeline(conn, demo)
    assert timeline is not None and timeline.events == []
    assert [u.entry_id for u in timeline.unprocessed_entries] == [UNPROCESSED_SEQ]
    names = _events(conn, demo)
    assert "fallback" in names and "run_end" in names
    logs = db.list_pipeline_logs(conn, "visit", demo)
    assert all("本文" not in str(r["decision"]) for r in logs)


async def test_build_failure_with_ai_result_retries_as_fallback(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = service.build_report_data

    def flaky(**kwargs: Any) -> Any:
        if not kwargs["result"].fallback:
            raise ValueError("AI の結果では組み立てられない")
        return original(**kwargs)

    monkeypatch.setattr(service, "build_report_data", flaky)
    await generate_visit_report(
        conn, demo, runner=_label_runner(conn), settings=settings
    )
    visit = db.get_visit(conn, demo)
    assert visit["status"] == "ready"
    assert visit["fallback"] is True
    html, data = db.get_report(conn, demo)
    assert data.fallback is True and "AI変換なし" in html
    logs = db.list_pipeline_logs(conn, "visit", demo)
    decisions = [r["decision"] for r in logs if r["event"] == "fallback"]
    assert "report_error:ValueError" in decisions


async def test_build_failure_marks_failed(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service, "build_report_data", _raiser(RuntimeError("組み立てられない"))
    )
    await generate_visit_report(
        conn, demo, runner=_label_runner(conn), settings=settings
    )
    visit = db.get_visit(conn, demo)
    assert visit["status"] == "failed"
    assert db.get_report(conn, demo) is None
    logs = db.list_pipeline_logs(conn, "visit", demo)
    failed = [r["decision"] for r in logs if r["event"] == "visit_failed"]
    assert failed == ["report_error:RuntimeError"]  # 1回だけ（型名つき）


async def test_render_failure_marks_failed(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "render_report_html", _raiser(ValueError("描けない")))
    await generate_visit_report(conn, demo, runner=FakeRunner(), settings=settings)
    assert db.get_visit(conn, demo)["status"] == "failed"


async def test_no_current_course_marks_failed(
    conn: sqlite3.Connection, settings: Any
) -> None:
    db.create_patient(conn, "FOLFOX", patient_id=PID)
    vid = _visit(conn)
    runner = FakeRunner()
    await generate_visit_report(conn, vid, runner=runner, settings=settings)

    assert runner.calls == 0
    assert db.get_visit(conn, vid)["status"] == "failed"
    logs = db.list_pipeline_logs(conn, "visit", vid)
    names = [r["event"] for r in logs]
    assert names[0] == "run_start" and "run_end" in names
    ends = [r["decision"] for r in logs if r["event"] == "run_end"]
    assert ends == ["prepare_error:PrepareInputError"]


async def test_unknown_skill_version_marks_failed(
    conn: sqlite3.Connection, settings: Any
) -> None:
    """記録の版の質問集が skill_versions に無い → 経過表を作れない → failed。"""
    db.create_patient(conn, "FOLFOX", patient_id=PID)
    for course in to_courses(DEMO):
        db.upsert_course(conn, course)
    _add_entry(conn, "下痢はなかった", jst_datetime(date(2026, 11, 8), 20))
    vid = _visit(conn)
    db.add_entry(
        conn,
        PID,
        EntryCreate(answers=[ClosedAnswer(question_key="diarrhea", value="none")]),
        jst_datetime(date(2026, 11, 6), 21),  # この日の記録はこれだけ
        "regimen-folfox@9",
    )
    await generate_visit_report(conn, vid, runner=FakeRunner(), settings=settings)
    assert db.get_visit(conn, vid)["status"] == "failed"


# ---------------------------------------------------------------------------
# 印刷済み・期限切れ
# ---------------------------------------------------------------------------


async def test_printed_visit_does_nothing(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    db.mark_printed(conn, demo)
    runner = _label_runner(conn)
    await generate_visit_report(conn, demo, runner=runner, settings=settings)

    assert runner.calls == 0
    visit = db.get_visit(conn, demo)
    assert visit["status"] == "printed"
    assert db.get_report(conn, demo) is None
    assert db.get_timeline(conn, demo) is None


@pytest.mark.parametrize("read_error", [False, True])
async def test_unknown_or_unreadable_visit_does_nothing(
    conn: sqlite3.Connection,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    read_error: bool,
) -> None:
    if read_error:  # 最初の読み込みの sqlite3.Error も外へ出さない
        locked = sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(service.db, "get_visit", _raiser(locked))
    runner = FakeRunner()
    await generate_visit_report(conn, 999, runner=runner, settings=settings)
    assert runner.calls == 0


class _PrintingRunner:
    """変換の途中で印刷済みにされる（生成が印刷より遅れて終わる）。"""

    def __init__(self, conn: sqlite3.Connection, vid: int) -> None:
        self.conn = conn
        self.vid = vid
        self.calls = 0

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        self.calls += 1
        db.mark_printed(self.conn, self.vid)
        return RunStats()


async def test_printed_during_generation_keeps_printed(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    runner = _PrintingRunner(conn, demo)
    await generate_visit_report(conn, demo, runner=runner, settings=settings)

    assert runner.calls == 1
    visit = db.get_visit(conn, demo)
    assert visit["status"] == "printed"
    assert visit["reception_no"] is None
    assert db.get_report(conn, demo) is None
    assert db.get_timeline(conn, demo) is None


async def test_printed_during_failure_keeps_printed(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(**kwargs: Any) -> Any:
        db.mark_printed(conn, demo)
        raise RuntimeError("組み立てられない")

    monkeypatch.setattr(service, "build_report_data", broken)
    await generate_visit_report(conn, demo, runner=FakeRunner(), settings=settings)
    assert db.get_visit(conn, demo)["status"] == "printed"
    names = _events(conn, demo)
    assert "visit_failed" not in names  # failed になっていないのに失敗と出さない
    assert names.count("visit_closed") == 1


# ---------------------------------------------------------------------------
# skill_versions
# ---------------------------------------------------------------------------


def test_ensure_skill_versions_registers_current_skills(
    conn: sqlite3.Connection,
) -> None:
    ensure_skill_versions(conn, SKILLS_DIR)
    folfox = load_regimen_skill("FOLFOX", SKILLS_DIR)
    capox = load_regimen_skill("CAPOX", SKILLS_DIR)
    report = load_report_skill(skills_dir=SKILLS_DIR)
    saved = db.get_skill_version(conn, folfox.name, folfox.version)
    assert saved is not None
    assert saved["content"] == (SKILLS_DIR / folfox.name / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert saved["questions"] == list(folfox.questions)
    assert db.get_skill_version(conn, capox.name, capox.version) is not None
    report_row = db.get_skill_version(conn, report.name, report.version)
    assert report_row is not None and report_row["questions"] is None
    ensure_skill_versions(conn, SKILLS_DIR)  # 何度呼んでもよい


def test_ensure_skill_versions_ignores_other_dirs(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    skills = tmp_path / "skills"
    target = skills / "regimen-folfox"
    target.mkdir(parents=True)
    text = (SKILLS_DIR / "regimen-folfox" / "SKILL.md").read_text(encoding="utf-8")
    (target / "SKILL.md").write_text(text, encoding="utf-8")
    (skills / "Not_A_Skill").mkdir()
    (skills / "regimen-empty").mkdir()  # SKILL.md が無い
    (skills / "README.md").write_text("x", encoding="utf-8")
    ensure_skill_versions(conn, skills)
    assert db.get_skill_version(conn, "regimen-folfox", 1) is not None
    assert db.latest_skill_version(conn, "regimen-empty") is None


def test_ensure_skill_versions_missing_dir_raises(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_skill_versions(conn, tmp_path / "nothing")


def test_questions_by_version(conn: sqlite3.Connection) -> None:
    assert questions_by_version(conn) == {}
    ensure_skill_versions(conn, SKILLS_DIR)
    folfox = load_regimen_skill("FOLFOX", SKILLS_DIR)
    capox = load_regimen_skill("CAPOX", SKILLS_DIR)
    got = questions_by_version(conn)
    assert got == {
        folfox.skill_version: list(folfox.questions),
        capox.skill_version: list(capox.questions),
    }
    shorter = list(folfox.questions)[:2]
    db.save_skill_version(conn, folfox.name, 2, "v2", shorter)
    assert questions_by_version(conn)[f"{folfox.name}@2"] == shorter


async def test_convert_exception_gives_fallback_ready(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("想定外")

    monkeypatch.setattr(service, "convert", broken)
    await generate_visit_report(conn, demo, runner=FakeRunner(), settings=settings)
    visit = db.get_visit(conn, demo)
    assert visit["status"] == "ready" and visit["fallback"] is True
    logs = db.list_pipeline_logs(conn, "visit", demo)
    fallbacks = [r["decision"] for r in logs if r["event"] == "fallback"]
    assert fallbacks == ["convert_error:RuntimeError"]


@pytest.mark.parametrize(
    "error",
    [sqlite3.OperationalError("database is locked"), db.NotFoundError("no visit")],
)
async def test_save_error_marks_failed(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    monkeypatch.setattr(service.db, "save_report", _raiser(error))
    await generate_visit_report(conn, demo, runner=FakeRunner(), settings=settings)
    assert db.get_visit(conn, demo)["status"] == "failed"
    logs = db.list_pipeline_logs(conn, "visit", demo)
    failed = [r["decision"] for r in logs if r["event"] == "visit_failed"]
    assert failed == [f"save_error:{type(error).__name__}"]


async def test_cancel_marks_failed_and_propagates(
    conn: sqlite3.Connection, demo: int, settings: Any
) -> None:
    runner = SlowRunner(30)
    task = asyncio.create_task(
        generate_visit_report(conn, demo, runner=runner, settings=settings)
    )
    while runner.calls == 0:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert db.get_visit(conn, demo)["status"] == "failed"
    logs = db.list_pipeline_logs(conn, "visit", demo)
    assert [r["decision"] for r in logs if r["event"] == "run_end"] == ["cancelled"]


# ---------------------------------------------------------------------------
# W2b 再修正: 受付番号の照合・競合・部分保存・skill_versions の境界
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reception_no, seq", [("3", 33), ("9", 36)])
async def test_short_numeric_reception_no_excludes_entries_for_now(
    conn: sqlite3.Connection, settings: Any, reception_no: str, seq: int
) -> None:
    """今の規則（部分文字列で照合）の固定。短い数字だけの受付番号では、ただの数字を
    含む記録（seq33「下痢が3回」・seq36「37.9」）も known_identifier で外れる（安全側）。
    照合規則が決まったら（契約への要望）このテストを書き換える。
    """
    _seed_demo(conn)
    vid = _visit(conn, reception_no)
    await generate_visit_report(conn, vid, runner=FakeRunner(), settings=settings)
    timeline = db.get_timeline(conn, vid)
    reasons = {u.entry_id: u.reason for u in timeline.unprocessed_entries}
    assert reasons[seq] == "known_identifier"
    assert db.get_visit(conn, vid)["status"] == "ready"


def _print_from_other_thread(
    path: Path, trigger: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> tuple[Callable[..., Any], list[threading.Thread], list[bool]]:
    """trigger の後の最初の get_visit（open の確認）の直後に、別の接続・別のスレッドで
    mark_printed する。直っていなければ 0.3 秒以内に印刷済みになってから service が進む。
    """
    original = db.get_visit
    threads: list[threading.Thread] = []
    blocked: list[bool] = []

    def get_visit(c: sqlite3.Connection, vid: int) -> Any:
        row = original(c, vid)
        if trigger.is_set() and not threads:
            other = db.connect(path)

            def run() -> None:
                try:
                    db.mark_printed(other, vid)
                finally:
                    other.close()

            thread = threading.Thread(target=run)
            threads.append(thread)
            thread.start()
            thread.join(0.3)  # 書き込みのロックで待たされれば戻らずに進む
            blocked.append(thread.is_alive())
        return row

    monkeypatch.setattr(service.db, "get_visit", get_visit)
    return original, threads, blocked


def _trigger_after_save(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    fired = threading.Event()
    original = db.save_report

    def save_report(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        fired.set()

    monkeypatch.setattr(service.db, "save_report", save_report)
    return fired


def _trigger_on_build_error(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    fired = threading.Event()

    def broken(**kwargs: Any) -> Any:
        fired.set()
        raise RuntimeError("組み立てられない")

    monkeypatch.setattr(service, "build_report_data", broken)
    return fired


def _print_inside_save(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """save_report の直後（再読込より前）に、同じスレッドで印刷済みにする。"""
    original = db.save_report

    def save_then_print(c: sqlite3.Connection, vid: int, *args: Any) -> None:
        original(c, vid, *args)
        db.mark_printed(c, vid)

    monkeypatch.setattr(service.db, "save_report", save_then_print)
    return threading.Event()  # 別スレッドは使わない


@pytest.mark.parametrize(
    "arm", [_print_inside_save, _trigger_after_save, _trigger_on_build_error]
)
async def test_printed_after_recheck_keeps_printed(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    tmp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arm: Callable[[pytest.MonkeyPatch], threading.Event],
) -> None:
    """保存の直後・再読込（open を確認）の直後で ready / failed にする直前に、印刷済みに
    される（後の2つは別の接続・別のスレッドから）。printed のまま、中身も消えたまま。
    """
    trigger = arm(monkeypatch)
    get_visit, threads, blocked = _print_from_other_thread(
        tmp_db_path, trigger, monkeypatch
    )
    await generate_visit_report(conn, demo, runner=FakeRunner(), settings=settings)
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    # 別スレッドの mark_printed は書き込みのロックで待たされ、service の後に入る
    assert blocked == ([True] if threads else [])
    if not threads:
        assert "visit_ready" not in _events(conn, demo)
    visit = get_visit(conn, demo)
    assert visit["status"] == "printed"
    assert visit["reception_no"] is None
    assert db.get_report(conn, demo) is None
    assert db.get_timeline(conn, demo) is None


@pytest.mark.xfail(
    strict=True,
    reason="db に3つの保存を1つのトランザクションにする・timeline を消す公開関数が"
    "無い（契約への要望）。service だけでは直せない",
)
async def test_save_error_leaves_no_timeline(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locked = sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(service.db, "save_report", _raiser(locked))
    await generate_visit_report(conn, demo, runner=FakeRunner(), settings=settings)
    assert db.get_visit(conn, demo)["status"] == "failed"
    assert db.get_timeline(conn, demo) is None


def _counting_get_skill_version(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []
    original = db.get_skill_version

    def counting(c: sqlite3.Connection, name: str, version: int) -> Any:
        calls.append((name, version))
        return original(c, name, version)

    monkeypatch.setattr(service.db, "get_skill_version", counting)
    return calls


HUGE_VERSION = 1_000_000


async def test_questions_by_version_fetch_is_bounded(
    conn: sqlite3.Connection,
    demo: int,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """版 100 万が1件あっても、1件ずつ 100 万回は引かない。"""
    folfox = load_regimen_skill("FOLFOX", SKILLS_DIR)
    shorter = list(folfox.questions)[:2]
    db.save_skill_version(conn, folfox.name, HUGE_VERSION, "huge", shorter)
    calls = _counting_get_skill_version(monkeypatch)
    huge = f"{folfox.name}@{HUGE_VERSION}"
    bad = ["@x", "@0", "@01", "@-1", "@1@1"]
    other = ["report-format-default@1", "regimen-unknown@1", "regimen-capox@7"]
    versions = [folfox.skill_version, folfox.skill_version, huge, *other]
    versions += [folfox.name + suffix for suffix in bad]
    got = questions_by_version(conn, versions=versions)
    assert got == {folfox.skill_version: list(folfox.questions), huge: shorter}
    assert len(calls) == 3  # folfox@1・folfox@1000000・capox@7 だけ

    calls.clear()
    with caplog.at_level(logging.WARNING, logger=service.__name__):
        got = questions_by_version(conn)  # 版を渡さない → 上限つきで順に引く
    assert len(calls) <= 2 * (service.MAX_SCANNED_VERSIONS + 1)
    assert got[folfox.skill_version] == list(folfox.questions)
    assert got[huge] == shorter  # 最新の版は必ず引く
    assert "MAX_SCANNED_VERSIONS" in caplog.text

    calls.clear()  # 生成は記録の版と今の版だけを引く
    await generate_visit_report(conn, demo, runner=FakeRunner(), settings=settings)
    assert db.get_visit(conn, demo)["status"] == "ready"
    assert len(calls) <= 2


def _broken_skill(conn: sqlite3.Connection, skills: Path) -> str:
    (skills / "regimen-aaa").mkdir()  # 名前順で最初に来る
    (skills / "regimen-aaa" / "SKILL.md").write_text("壊れた本文", encoding="utf-8")
    return "SkillFormatError"


def _conflicting_version(conn: sqlite3.Connection, skills: Path) -> str:
    """同じ版が別の内容で登録済み（版を上げずに書き換えた）。"""
    capox = load_regimen_skill("CAPOX", SKILLS_DIR)
    questions = list(capox.questions)
    db.save_skill_version(conn, capox.name, capox.version, "前の内容", questions)
    return "ValueError"


@pytest.mark.parametrize("setup", [_broken_skill, _conflicting_version])
def test_ensure_skill_versions_skips_bad_skill_and_continues(
    conn: sqlite3.Connection,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    setup: Callable[[sqlite3.Connection, Path], str],
) -> None:
    """壊れた Skill・版の衝突が1つあっても、警告（型名だけ）して残りを登録する。"""
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, skills)
    error_type = setup(conn, skills)
    with caplog.at_level(logging.WARNING, logger=service.__name__):
        ensure_skill_versions(conn, skills)  # 起動を止めない
    for name in ("regimen-capox", "regimen-folfox", "report-format-default"):
        assert db.latest_skill_version(conn, name) is not None
    assert db.latest_skill_version(conn, "regimen-aaa") is None
    capox = db.get_skill_version(conn, "regimen-capox", 1)
    if error_type == "ValueError":
        assert capox["content"] == "前の内容"  # 上書きしない
    assert error_type in caplog.text
    assert "壊れた本文" not in caplog.text and "前の内容" not in caplog.text

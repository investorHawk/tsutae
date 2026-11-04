"""デモの筋書きを通す結合テスト（test_e2e_flow.py）の部品。API は呼ばない。

- `demo_client`: backend/skills_home を tmp_path に写し（D4 の承認で本物の SKILL.md を
  書き換えない）、合成3人を投入した TestClient を開く
- `demo_runner`: いまの DB の記録から、サービスと同じ引数で `prepare_input` を作り、
  正解ラベル（labels_demo_patient.json）から AI の結果（emit_timeline・emit_report）を
  作った台本どおりの FakeRunner。患者画面から足した記録（ラベルなし）は出来事にしない
- 医師の Cookie は `POST /api/doctor/login` で取る（12時間で失効するので、
  TSUTAE_TODAY を進めたら取り直す）
- `expected_pipeline_input`: Claude への入力の期待値を、合成データの JSON と患者画面から
  足した記録から**独立に**数え上げる（prepare_input・course・masking を使わない）
- `InterruptingRunner`: 生成の途中（runner の中）で受診を閉じ（印刷済み・期限切れ）、
  その後で台本を流す（閉じた受診を保存で生き返らせないことを試す）
- 症例は全て合成
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from api_helpers import (
    TEST_PASSWORD,
    FakeEditor,
    RunnerFactory,
    api_client,
    db_conn,
    seed_synthetic,
)
from claude_agent_sdk import ClaudeAgentOptions
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner, label_payloads, load_case, standard_steps

from tsutae import db
from tsutae.api.deps import DOCTOR_COOKIE, make_doctor_token
from tsutae.config import SKILLS_HOME, SYNTHETIC_DIR, now, today
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.prompt import JSON_FENCE
from tsutae.pipeline.tools import RunCollector
from tsutae.schemas import PreparedInput, RunStats
from tsutae.skills import load_regimen_skill, load_report_skill

DEMO_CASE = "demo_patient"
DEMO_PID = "P-DEMO0001"
DEMO_RECEPTION = "A-023"
UNPROCESSED_SEQ = 38  # 二次検出に掛かる記載（辞書にない架空の姓＋さん。D6 デモ用）
NEW_QUESTION_KEY = "meal_intake"
NEW_QUESTION_TEXT = "口内炎で食事がとりにくいことはありましたか"
NEW_QUESTION_LINE = (
    f"  - {{key: {NEW_QUESTION_KEY}, text: {NEW_QUESTION_TEXT}, "
    "answer_type: three_level}\n"
)
_ANCHOR = "  - {key: fever,"
_ROW_CELL = re.compile(
    r'<td class="(?P<cls>[^"]*)" data-row="(?P<row>[^"]+)" data-day="(?P<day>\d+)">'
    r"(?P<body>.*?)</td>"
)


# ---------------------------------------------------------------------------
# アプリ
# ---------------------------------------------------------------------------


def copy_skills_home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


@contextmanager
def demo_client(
    tmp_path: Path,
    *,
    runner: Any = None,
    editor: Any = None,
    **overrides: Any,
) -> Iterator[TestClient]:
    """写した Skill を使い、合成3人を投入した TestClient（デモ患者を最初に入れる）。

    overrides は Settings の上書き（例 `pipeline_timeout_s=0.05`）。
    """
    home = copy_skills_home(tmp_path)
    with api_client(
        tmp_path,
        runner=runner,
        editor=editor,
        skills_dir=home / ".claude" / "skills",
        **overrides,
    ) as client:
        added = seed_synthetic(client.app)
        assert added[0] == DEMO_PID, added
        yield client


def set_runner(client: TestClient, runner: Any) -> None:
    """次の受付から使う runner（run_generation は受付のときに factory を引く）。"""
    client.app.state.runner_factory = RunnerFactory(runner)


def doctor_login(client: TestClient) -> None:
    r = client.post("/api/doctor/login", json={"password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def skill_file(client: TestClient, name: str = "regimen-folfox") -> Path:
    return Path(client.app.state.settings.skills_dir) / name / "SKILL.md"


# ---------------------------------------------------------------------------
# 台本（正解ラベル → AI の結果）
# ---------------------------------------------------------------------------


def _seq_by_entry_id(client: TestClient, pid: str) -> dict[int, int]:
    """DB の記録の id → 合成データの seq（記録日時で対応づける）。"""
    patient, _labels = load_case(DEMO_CASE)
    seq_by_time = {e.recorded_at: e.seq for e in patient.entries}
    with db_conn(client.app) as conn:
        entries = db.list_entries(conn, pid)
    return {
        e.id: seq_by_time[e.recorded_at]
        for e in entries
        if e.recorded_at in seq_by_time
    }


def live_prepared(client: TestClient, pid: str, reception_no: str) -> PreparedInput:
    """サービス（generate_visit_report）と同じ引数で、いまの DB から入力を作る。"""
    skills_dir = client.app.state.settings.skills_dir
    with db_conn(client.app) as conn:
        patient = db.get_patient(conn, pid)
        assert patient is not None
        courses = db.list_courses(conn, pid)
        entries = db.list_entries(conn, pid)
    return prepare_input(
        courses=courses,
        entries=entries,
        regimen_skill=load_regimen_skill(patient["regimen"], skills_dir),
        report_skill=load_report_skill(skills_dir=skills_dir),
        visit_date=today(),
        exclude_literals=(pid, reception_no),
    )


def demo_runner(
    client: TestClient, pid: str = DEMO_PID, reception_no: str = DEMO_RECEPTION
) -> FakeRunner:
    """正解ラベルから作った台本（Skill → 3役 → emit_timeline → emit_report）。"""
    prepared = live_prepared(client, pid, reception_no)
    seq_by_id = _seq_by_entry_id(client, pid)
    # label_payloads は entry_ids の値を seq とみなす。ラベルの無い記録は負の値にする
    as_seq = prepared.model_copy(
        update={
            "entry_ids": {
                no: seq_by_id.get(eid, -eid) for no, eid in prepared.entry_ids.items()
            }
        }
    )
    timeline, report = label_payloads(DEMO_CASE, as_seq)
    assert timeline["events"] and timeline["contradictions"]
    return FakeRunner(standard_steps(timeline, report))


# ---------------------------------------------------------------------------
# 受付・医師画面
# ---------------------------------------------------------------------------


def post_visit(client: TestClient, reception_no: str) -> dict[str, Any]:
    """受付（TestClient はバックグラウンドの生成の完了まで待つ）→ 一覧のその受診。"""
    r = client.post("/api/visit", json={"reception_no": reception_no})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "message_key": "visit.done"}
    visit = find_visit(client, reception_no)
    assert visit is not None
    return visit


def doctor_visits(client: TestClient) -> list[dict[str, Any]]:
    r = client.get("/api/doctor/visits")
    assert r.status_code == 200, r.text
    return r.json()["visits"]


def find_visit(client: TestClient, reception_no: str) -> dict[str, Any] | None:
    found = [v for v in doctor_visits(client) if v["reception_no"] == reception_no]
    assert len(found) <= 1
    return found[0] if found else None


def report_html(client: TestClient, visit_id: int) -> str:
    r = client.get(f"/api/doctor/visits/{visit_id}/report")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    return r.text


def grid_row(html: str, row_id: str) -> dict[int, tuple[str, str]]:
    """経過表の1行: Day → (class, セルの中身の HTML)。row_id は `c3-diarrhea` の形。"""
    return {
        int(m["day"]): (m["cls"], m["body"])
        for m in _ROW_CELL.finditer(html)
        if m["row"] == row_id
    }


def section(html: str, name: str) -> str:
    """`<section class="<name>">` の中身（無ければ空文字）。"""
    m = re.search(rf'<section class="{name}[^"]*">(.*?)</section>', html, re.S)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# D4（質問を1つ足す偽の editor）
# ---------------------------------------------------------------------------


def add_question(text: str) -> str:
    """questions の fever の前に質問を1行足す（version は変えない）。"""
    assert _ANCHOR in text and NEW_QUESTION_KEY not in text
    return text.replace(_ANCHOR, NEW_QUESTION_LINE + _ANCHOR, 1)


def question_adding_editor() -> FakeEditor:
    transform: Callable[[str], str] = add_question
    return FakeEditor(transform=transform)


# ---------------------------------------------------------------------------
# 医師の Cookie（無し・改ざん・失効）と医師 API の一覧
# ---------------------------------------------------------------------------


def bad_doctor_tokens(client: TestClient) -> dict[str, str | None]:
    """認証に通らない医師 Cookie の値（None は Cookie 無し）。"""
    secret = client.app.state.settings.secret_key
    valid = make_doctor_token(secret, now())
    flipped = valid[:-1] + ("0" if valid[-1] != "0" else "1")
    return {
        "missing": None,
        "tampered": flipped,
        "wrong_secret": make_doctor_token(secret + "-other", now()),
        "expired": make_doctor_token(secret, now() - timedelta(hours=12, minutes=1)),
    }


@contextmanager
def doctor_cookie(client: TestClient, value: str | None) -> Iterator[None]:
    """医師 Cookie を value に差し替え（None なら外し）、抜けるときに元へ戻す。"""
    saved = client.cookies.get(DOCTOR_COOKIE)
    client.cookies.delete(DOCTOR_COOKIE)
    if value is not None:
        client.cookies.set(DOCTOR_COOKIE, value)
    try:
        yield
    finally:
        client.cookies.delete(DOCTOR_COOKIE)
        if saved is not None:
            client.cookies.set(DOCTOR_COOKIE, saved)


def doctor_calls(
    visit_id: int, pid: str = DEMO_PID, change_id: int = 1
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """医師 API（login/logout 以外）の (メソッド, 経路, 本文)。本文・経路は正しい形にする。"""
    course = {"patient_id": pid, "course_no": 4, "infusion_date": "2026-11-10"}
    change = {"skill_name": "regimen-folfox", "request_text": "口内炎の質問を足して"}
    return [
        ("GET", "/api/doctor/patients", None),
        ("POST", "/api/doctor/patients", {"regimen": "FOLFOX"}),
        ("GET", f"/api/doctor/patients/{pid}/courses", None),
        ("GET", f"/api/doctor/patients/{pid}/visits", None),
        ("GET", f"/api/doctor/patients/{pid}/entries", None),
        ("POST", "/api/doctor/courses", course),
        ("GET", "/api/doctor/visits", None),
        ("GET", f"/api/doctor/visits/{visit_id}/report", None),
        ("POST", f"/api/doctor/visits/{visit_id}/printed", None),
        ("GET", f"/api/doctor/visits/{visit_id}/unprocessed", None),
        ("GET", f"/api/doctor/pipeline/{visit_id}/events", None),
        ("GET", "/api/doctor/skills", None),
        ("GET", "/api/doctor/skills/regimen-folfox", None),
        ("GET", "/api/doctor/skill-changes", None),
        ("POST", "/api/doctor/skill-changes", change),
        ("POST", f"/api/doctor/skill-changes/{change_id}/approve", None),
        ("POST", f"/api/doctor/skill-changes/{change_id}/reject", None),
    ]


# ---------------------------------------------------------------------------
# Claude への入力の独立な期待値（合成データ → PipelineInput の JSON）
# ---------------------------------------------------------------------------

# デモ患者の受診日 2026-11-09 の今コース（C3）。docs/architecture.md §6 の筋書きから
C3_SCHEDULE = {
    "course_no": 3,
    "infusion_date": "2026-10-27",
    "day1_date": "2026-10-27",
    "last_day_date": "2026-11-09",  # 次コース未登録 → 実投与日 + 14 - 1
    "pump_removal_date": "2026-10-29",  # Day3
    "previous_infusion_date": "2026-10-13",
    "delay_days": 0,  # 予定どおり
}
_C3_DAY1 = date(2026, 10, 27)
_C3_LAST = date(2026, 11, 9)
# 一次置換で変わる記載（それ以外の C3 の自由記載はそのまま送る）
MASKED_REPLACEMENTS = {40: ("佐藤先生", "○○先生")}
EXCLUDED_SEQS = {UNPROCESSED_SEQ}  # 二次検出に掛かる記録は送らない


def prompt_input(prompt: str) -> dict[str, Any]:
    """依頼文の末尾の PipelineInput の JSON を読む。"""
    assert prompt.count(JSON_FENCE) == 1
    _head, tail = prompt.split(JSON_FENCE, 1)
    assert tail.endswith("\n```\n")
    return json.loads(tail[: -len("\n```\n")])


def _expected_answers(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "question_key": a["question_key"],
            "value": a["value"],
            "temperature": a.get("temperature"),
        }
        for a in raw
    ]


def _expected_entry(
    record_date: date, raw: Mapping[str, Any], masked: str | None
) -> dict[str, Any]:
    return {
        "record_date": record_date.isoformat(),
        "day": (record_date - _C3_DAY1).days + 1,
        "by_proxy": bool(raw.get("by_proxy", False)),
        "too_sick": bool(raw.get("too_sick", False)),
        "answers": _expected_answers(raw.get("answers", [])),
        "masked_free_text": masked,
    }


def _masked(seq: int, text: str | None) -> str | None:
    if text is None or seq not in MASKED_REPLACEMENTS:
        return text
    old, new = MASKED_REPLACEMENTS[seq]
    assert old in text
    return text.replace(old, new)


def _synthetic_c3_entries() -> list[dict[str, Any]]:
    raw = json.loads((SYNTHETIC_DIR / f"{DEMO_CASE}.json").read_text("utf-8"))
    out: list[dict[str, Any]] = []
    for e in sorted(raw["entries"], key=lambda x: x["recorded_at"]):
        record_date = date.fromisoformat(e["recorded_at"][:10])  # 全て +09:00
        if not _C3_DAY1 <= record_date <= _C3_LAST or e["seq"] in EXCLUDED_SEQS:
            continue
        out.append(_expected_entry(record_date, e, _masked(e["seq"], e["free_text"])))
    return out


def expected_pipeline_input(
    today_bodies: Sequence[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """受診日（今日 = C3 の最終日）の PipelineInput の期待値。

    today_bodies は患者画面から今日足した記録（POST の本文、足した順）。
    questions は患者 API の質問集（Skill の frontmatter と同じもの）。
    """
    added = [_expected_entry(_C3_LAST, b, b.get("free_text")) for b in today_bodies]
    entries = [
        {"entry_no": no, **e}
        for no, e in enumerate(_synthetic_c3_entries() + added, start=1)
    ]
    return {
        "regimen": "FOLFOX",
        "regimen_skill_version": "regimen-folfox@1",
        "report_skill_version": "report-format-default@1",
        "schedule": C3_SCHEDULE,
        "questions": [dict(q) for q in questions],
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# 生成の途中で受診を閉じる runner
# ---------------------------------------------------------------------------


class InterruptingRunner:
    """run の中（生成の途中）で interrupt を呼び、その後で inner に台本を流す。"""

    def __init__(self, inner: Any, interrupt: Callable[[], None]) -> None:
        self.inner = inner
        self.interrupt = interrupt
        self.calls = 0

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        self.calls += 1
        self.interrupt()
        return await self.inner.run(prompt, options, collector)


def close_visit(client: TestClient, how: str) -> Callable[[], None]:
    """生成中の受診を閉じる関数（別の接続で）。how は printed か expired。"""

    def close() -> None:
        with db_conn(client.app) as conn:
            (visit,) = db.list_visits(conn, ("generating",))
            assert visit["reception_no"] is not None
            if how == "printed":
                db.mark_printed(conn, visit["id"])
            elif how == "expired":
                later = now() + timedelta(hours=24, minutes=1)
                assert db.purge_expired(conn, later) == 1
            else:
                raise ValueError(how)

    return close

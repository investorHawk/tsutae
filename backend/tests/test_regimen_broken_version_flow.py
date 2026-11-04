"""T95 の確かめ直し: 古い版の全文が今の検査に通らなくても、受診の紙は出る。

skill_versions の版1 の content の frontmatter を 'version: 9' に書き換える（質問集の列は
そのまま）。記録ごとの用語の対応の材料（`regimen_skills_by_version`）は版1 を引けない。

- 版1 の記録は安全側: どの用語も質問につなげない（question_key=null。○ を付けない）。
  出来事は紙に残る
- AI 変換あり・なし（timeline=None のフォールバック）のどちらも紙が出る。T95 の直後は
  gate が skill_mismatch を出し、フォールバックも同じ gate を通るので受診が failed だった
- 警告のログは版の名前と番号だけ（全文・記録の文は出さない）

作りは test_regimen_mixed_versions_flow.py に倣う（API を呼ばない偽の runner）。
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import api_client, db_conn, login_doctor, register
from claude_agent_sdk import ClaudeSDKError
from e2e_scripts import grid_row, live_prepared, post_visit, report_html, section
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner, RaisingRunner, standard_steps
from test_regimen_mixed_versions_flow import (
    INFUSION,
    NAME,
    RECEPTION,
    _adopt_v1,
    _event,
    _place_v2,
    _record,
)

from tsutae.config import SKILLS_HOME

V1 = f"{NAME}@1"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


@pytest.fixture
def client(tmp_path: Path, home: Path, fixed_today: str) -> Iterator[TestClient]:
    with api_client(tmp_path, skills_dir=home / ".claude" / "skills") as c:
        _adopt_v1(c, home)
        login_doctor(c)
        yield c


def _break_v1(client: TestClient) -> None:
    """版1 の全文の frontmatter の版だけを書き換える（質問集の列は残る）。"""
    with db_conn(client.app) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE skill_versions SET content = replace(content, ?, ?)"
                " WHERE skill_name = ? AND version = 1",
                ("version: 1", "version: 9", NAME),
            )
        assert cur.rowcount == 1
        row = conn.execute(
            "SELECT content, questions_json FROM skill_versions"
            " WHERE skill_name = ? AND version = 1",
            (NAME,),
        ).fetchone()
    assert "version: 9" in row[0] and row[1] is not None


def _patient_with_mixed_records(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> str:
    r = client.post("/api/doctor/patients", json={"regimen": "RAM-WPTX"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(
        "/api/doctor/courses",
        json={"patient_id": pid, "course_no": 1, "infusion_date": INFUSION},
    )
    assert r.status_code == 200, r.text
    assert register(client, pid).status_code == 200
    _record(client, pid, V1, "今日はだるい")
    _place_v2(client)
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-10")
    _record(client, pid, f"{NAME}@2", "今日もだるい")
    _break_v1(client)
    login_doctor(client)
    return pid


def _runner(client: TestClient, pid: str) -> FakeRunner:
    prepared = live_prepared(client, pid, RECEPTION)
    assert prepared.other_versions[V1].question_keys == []  # 材料を引けなかった
    first, second = prepared.input.entries
    events = [
        _event(first.entry_no, first.record_date.isoformat(), 8, None),
        _event(second.entry_no, second.record_date.isoformat(), 9, "fatigue"),
    ]
    per_symptom: list[dict[str, Any]] = [
        {
            "term": "倦怠感",
            "question_key": None,
            "start_day": 8,
            "start_date": first.record_date.isoformat(),
            "representative_quote": "だるい",
            "confidence": 0.9,
        }
    ]
    timeline = {"events": events, "contradictions": []}
    return FakeRunner(standard_steps(timeline, {"per_symptom": per_symptom}, NAME))


def _assert_warned_name_only(caplog: pytest.LogCaptureFixture) -> None:
    assert V1 in caplog.text
    assert "だるい" not in caplog.text and "version: 9" not in caplog.text


def test_report_is_printed_with_broken_old_version(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    pid = _patient_with_mixed_records(client, monkeypatch)
    caplog.set_level(logging.WARNING, logger="tsutae.pipeline")
    runner = _runner(client, pid)
    client.app.state.runner_factory.runner = runner
    visit = post_visit(client, RECEPTION)
    assert all(o.decision == "allow" for o in runner.outcomes), runner.outcomes
    assert visit["status"] == "ready" and visit["fallback"] is False, visit

    html = report_html(client, visit["id"])
    fatigue = grid_row(html, "c1-fatigue")
    cls8, body8 = fatigue[8]
    assert "st-not_asked" in cls8 and "○" not in body8
    cls9, body9 = fatigue[9]
    assert "st-present" in cls9 and "○" in body9
    assert "だるい" in section(html, "quotes")
    _assert_warned_name_only(caplog)


def test_fallback_report_is_printed_with_broken_old_version(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patient_with_mixed_records(client, monkeypatch)
    caplog.set_level(logging.WARNING, logger="tsutae.pipeline")
    client.app.state.runner_factory.runner = RaisingRunner(ClaudeSDKError("boom"))
    visit = post_visit(client, RECEPTION)
    assert visit["status"] == "ready" and visit["fallback"] is True, visit

    html = report_html(client, visit["id"])
    assert "AI変換なし" in html
    fatigue = grid_row(html, "c1-fatigue")
    assert "st-not_asked" in fatigue[8][0]
    assert all("○" not in body for _cls, body in fatigue.values())
    _assert_warned_name_only(caplog)

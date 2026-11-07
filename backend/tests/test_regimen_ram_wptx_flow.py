"""T95 の通し: D4 で採用した RAM＋wPTX の患者を登録して記録 → 受診 → レポート。

API を呼ばない構成（偽の runner）。採用は T93 の関数（下書き → 直接編集 → 確認 → 採用）で
一時の skills_home に `regimen-ram-wptx` を置いてから、医師 API で患者を登録する。

- 医師のレジメンの一覧に RAM-WPTX（表示名 RAM＋wPTX）が出て、その患者を登録できる
- 患者の質問は `regimen-ram-wptx@1`（だるさ・出血・しびれの新しい質問つき）
- 自由記載の「だるい」は、版の term_keys で 倦怠感 → fatigue につながる（全体の対応では
  null）。しびれは 末梢神経障害 → neuropathy（全体の対応では numbness）
- 紙: ヘッダは表示名、経過表の行は form の短い名前（だるさ）、○ が付く
- 医師画面（D2）の記録の回答に短い名前が付く
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import api_client, db_conn, login_doctor, record_entry, register
from e2e_scripts import grid_row, live_prepared, post_visit, report_html, section
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner, standard_steps
from regimen_fixtures import extra_form, fill_patch

from tsutae.config import SKILLS_HOME
from tsutae.masking import detect_identifiers
from tsutae.pipeline.prompt import build_prompt
from tsutae.regimen.adopt import adopt
from tsutae.regimen.drafts import create_new_draft, draft_form, patch_draft
from tsutae.regimen.preview import build_preview

TIMEOUT = 90.0
RECEPTION = "B-101"
INFUSION = "2026-11-02"  # Day1（今日 2026-11-09 は Day8）
FREE_TEXT = "今日はだるい。手足のしびれもある"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


@pytest.fixture
def client(tmp_path: Path, home: Path, fixed_today: str) -> Iterator[TestClient]:
    with api_client(tmp_path, skills_dir=home / ".claude" / "skills") as c:
        _adopt_ram_wptx(c, home)
        login_doctor(c)
        yield c


def _adopt_ram_wptx(client: TestClient, home: Path) -> None:
    skills_dir = home / ".claude" / "skills"
    with db_conn(client.app) as conn:
        draft = create_new_draft(conn)
        patch = fill_patch(draft_form(draft), extra_form("ram_wptx"))
        draft = patch_draft(
            conn, draft["id"], patch, skills_dir=skills_dir, timeout_s=TIMEOUT
        )
        preview = build_preview(conn, draft, skills_dir=skills_dir)
        assert preview["issues"] == []
        result = adopt(
            conn,
            draft["id"],
            preview["confirm_token"],
            True,
            skills_home=home,
            timeout_s=TIMEOUT,
        )
    assert (result.skill_name, result.version) == ("regimen-ram-wptx", 1)


def _create_patient(client: TestClient) -> str:
    r = client.post("/api/doctor/patients", json={"regimen": "RAM-WPTX"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(
        "/api/doctor/courses",
        json={"patient_id": pid, "course_no": 1, "infusion_date": INFUSION},
    )
    assert r.status_code == 200, r.text
    return pid


def _answers() -> list[dict[str, Any]]:
    values = {
        "neuropathy": "present",
        "diarrhea": "none",
        "stomatitis": "none",
        "nausea_appetite": "none",
        "fatigue": "present",
        "bleeding": "none",
    }
    out: list[dict[str, Any]] = [
        {"question_key": k, "value": v} for k, v in values.items()
    ]
    return [*out, {"question_key": "fever", "value": "not_measured"}]


def _record(client: TestClient, pid: str) -> None:
    assert register(client, pid).status_code == 200
    body = client.get(f"/api/patient/{pid}/questions").json()
    assert body["skill_version"] == "regimen-ram-wptx@1"
    assert {"fatigue", "bleeding", "neuropathy"} <= {
        q["key"] for q in body["questions"]
    }
    record_entry(client, pid, {"answers": _answers(), "free_text": FREE_TEXT})


def _event(no: int, d: str, term: str, key: str, quote: str) -> dict[str, Any]:
    return {
        "entry_no": no,
        "date": d,
        "day": 8,
        "course_no": 1,
        "term": term,
        "question_key": key,
        "status": "present",
        "source_quote": quote,
        "confidence": 0.9,
        "recalled": False,
        "by_proxy": False,
    }


def _runner(client: TestClient, pid: str) -> FakeRunner:
    prepared = live_prepared(client, pid, RECEPTION)
    assert detect_identifiers(build_prompt(prepared)) == []
    (entry,) = prepared.input.entries
    d = entry.record_date.isoformat()
    events = [
        _event(entry.entry_no, d, "倦怠感", "fatigue", "今日はだるい"),
        _event(entry.entry_no, d, "末梢神経障害", "neuropathy", "手足のしびれ"),
    ]
    per_symptom = [
        {
            "term": ev["term"],
            "question_key": ev["question_key"],
            "start_day": 8,
            "start_date": d,
            "representative_quote": ev["source_quote"],
            "confidence": 0.9,
        }
        for ev in events
    ]
    timeline = {"events": events, "contradictions": []}
    return FakeRunner(
        standard_steps(timeline, {"per_symptom": per_symptom}, "regimen-ram-wptx")
    )


def test_regimen_list_shows_adopted_regimen(client: TestClient) -> None:
    r = client.get("/api/doctor/regimens")
    assert r.status_code == 200, r.text
    by_code = {g["code"]: g for g in r.json()["regimens"]}
    assert by_code["RAM-WPTX"] == {
        "code": "RAM-WPTX",
        "skill_name": "regimen-ram-wptx",
        "version": 1,
        "display_name": "RAM＋wPTX",
    }
    assert by_code["FOLFOX"]["display_name"] == "FOLFOX"


def test_ram_wptx_patient_records_visit_and_report(client: TestClient) -> None:
    pid = _create_patient(client)
    _record(client, pid)
    runner = _runner(client, pid)
    client.app.state.runner_factory.runner = runner

    visit = post_visit(client, RECEPTION)
    assert all(o.decision == "allow" for o in runner.outcomes), runner.outcomes
    assert visit["status"] == "ready" and visit["fallback"] is False, visit

    html = report_html(client, visit["id"])
    assert "RAM＋wPTX" in section(html, "header")
    grid = section(html, "grid")
    assert ">だるさ<" in grid and ">出血<" in grid
    assert "だるさや疲れやすさはありましたか" not in grid  # 質問文ではなく短い名前
    fatigue = grid_row(html, "c1-fatigue")
    assert "st-present" in fatigue[8][0] and "○" in fatigue[8][1]
    neuropathy = grid_row(html, "c1-neuropathy")
    assert "○" in neuropathy[8][1]
    assert "倦怠感" in section(html, "per-symptom")


def test_doctor_entries_carry_short_labels(client: TestClient) -> None:
    pid = _create_patient(client)
    _record(client, pid)
    login_doctor(client)
    r = client.get(f"/api/doctor/patients/{pid}/entries")
    assert r.status_code == 200, r.text
    (entry,) = r.json()["entries"]
    labels = {a["question_key"]: a["question_label"] for a in entry["answers"]}
    assert labels["fatigue"] == "だるさ"
    assert labels["bleeding"] == "出血"
    assert labels["diarrhea"] == "下痢"

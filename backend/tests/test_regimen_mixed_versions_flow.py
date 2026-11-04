"""T95 の通し: 版の混ざる受診で、自由記載の出来事は記録の版の質問の行にだけつながる。

spec 9.1「変換の検査（出来事の question_key）と紙の検査は、その記録の Skill の版の対応」。
API を呼ばない構成（偽の runner）。

- 版1（だるさの質問なし）を T93 の採用の関数で置き、患者を登録して Day8 に「だるい」を記録
- 版2（だるさを足した。倦怠感 → fatigue）を置き、Day9 に「だるい」とだるさの回答を記録
- 受診の変換: 版1 の記録の 倦怠感 は null、版2 の記録は fatigue で checks を通る
  （service が skill_versions から記録の版の Skill を引いて prepare_input に渡す）
- 紙: だるさの行は Day8 が未設問（−−）で ○ なし、Day9 は回答と ○
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import api_client, db_conn, login_doctor, register
from e2e_scripts import grid_row, live_prepared, post_visit, report_html
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner, standard_steps
from regimen_fixtures import extra_form, fill_patch, ram_wptx_data

from tsutae import db
from tsutae.config import SKILLS_HOME
from tsutae.regimen import RegimenForm, render_regimen_skill
from tsutae.regimen.adopt import adopt
from tsutae.regimen.drafts import create_new_draft, draft_form, patch_draft
from tsutae.regimen.preview import build_preview
from tsutae.skills import validate_skill_text

TIMEOUT = 90.0
NAME = "regimen-ram-wptx"
RECEPTION = "B-102"
INFUSION = "2026-11-02"  # Day1（2026-11-09 は Day8、2026-11-10 は Day9）


def _without_fatigue() -> RegimenForm:
    data = ram_wptx_data()
    data["questions"] = [q for q in data["questions"] if q["key"] != "fatigue"]
    data["side_effects"] = [
        {**s, "question_key": None} if s["question_key"] == "fatigue" else s
        for s in data["side_effects"]
    ]
    return RegimenForm.model_validate(data)


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


def _adopt_v1(client: TestClient, home: Path) -> None:
    skills_dir = home / ".claude" / "skills"
    with db_conn(client.app) as conn:
        draft = create_new_draft(conn)
        patch = fill_patch(draft_form(draft), _without_fatigue())
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
    assert (result.skill_name, result.version) == (NAME, 1)


def _place_v2(client: TestClient) -> None:
    """版2（だるさの質問・倦怠感 → fatigue）を置いて skill_versions に登録する。"""
    text = render_regimen_skill(extra_form("ram_wptx"), 2)
    skill = validate_skill_text(NAME, text)
    path = client.app.state.settings.skills_dir / NAME / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    with db_conn(client.app) as conn:
        db.save_skill_version(conn, NAME, 2, text, list(skill.questions))


def _record(client: TestClient, pid: str, version: str, text: str) -> None:
    body = client.get(f"/api/patient/{pid}/questions").json()
    assert body["skill_version"] == version
    answers: list[dict[str, Any]] = [
        {"question_key": q["key"], "value": "present"}
        for q in body["questions"]
        if q["answer_type"] == "three_level"
    ]
    answers.append({"question_key": "fever", "value": "not_measured"})
    r = client.post(
        f"/api/patient/{pid}/entries", json={"answers": answers, "free_text": text}
    )
    assert r.status_code == 200, r.text


def _event(no: int, d: str, day: int, key: str | None) -> dict[str, Any]:
    return {
        "entry_no": no,
        "date": d,
        "day": day,
        "course_no": 1,
        "term": "倦怠感",
        "question_key": key,
        "status": "present",
        "source_quote": "だるい",
        "confidence": 0.9,
        "recalled": False,
        "by_proxy": False,
    }


def _runner(client: TestClient, pid: str) -> FakeRunner:
    prepared = live_prepared(client, pid, RECEPTION)
    first, second = prepared.input.entries
    events = [
        _event(first.entry_no, first.record_date.isoformat(), 8, None),
        _event(second.entry_no, second.record_date.isoformat(), 9, "fatigue"),
    ]
    per_symptom = [
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


def test_events_follow_record_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = client.post("/api/doctor/patients", json={"regimen": "RAM-WPTX"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(
        "/api/doctor/courses",
        json={"patient_id": pid, "course_no": 1, "infusion_date": INFUSION},
    )
    assert r.status_code == 200, r.text
    assert register(client, pid).status_code == 200
    _record(client, pid, f"{NAME}@1", "今日はだるい")
    _place_v2(client)
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-10")
    _record(client, pid, f"{NAME}@2", "今日もだるい")

    login_doctor(client)
    runner = _runner(client, pid)
    client.app.state.runner_factory.runner = runner
    visit = post_visit(client, RECEPTION)
    assert all(o.decision == "allow" for o in runner.outcomes), runner.outcomes
    assert visit["status"] == "ready" and visit["fallback"] is False, visit

    html = report_html(client, visit["id"])
    fatigue = grid_row(html, "c1-fatigue")
    cls8, body8 = fatigue[8]
    assert "st-not_asked" in cls8 and "○" not in body8  # 版1 では聞いていない
    cls9, body9 = fatigue[9]
    assert "st-present" in cls9 and "○" in body9

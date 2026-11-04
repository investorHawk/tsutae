"""医師 API: 未処理の記載（D6）の伏せ字（確かめる・保存）と、変換し直し。症例は全て合成。

- `POST /api/doctor/visits/{id}/masks/check {entry_id, spans}`: 区間を当てた後の文と、
  まだ疑われる区間を返す（保存しない）
- `POST /api/doctor/visits/{id}/masks {entries: [{entry_id, send, spans, confirmed_clear}]}`:
  送る記録は医師の伏せ字を保存、送らない記録は消す。閉じた受診は 409 visit_closed、
  生成中は 409 generating
- 医師の伏せ字がある開いた受診は、AI の結果で ready でも regenerate できる。伏せた記録は
  Claude への依頼文に `[伏せ字]` で入り、未処理から外れる。確かめた記録は H1 を通る
- ログは文面なし（`doctor_mask_saved` 等、decision は `entry:<id>` だけ）
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import (
    RunnerFactory,
    api_client,
    db_conn,
    login_doctor,
    register,
    seed_synthetic,
)
from fastapi.testclient import TestClient
from pipeline_fakes import (
    FakeRunner,
    label_payloads,
    load_case,
    regimen_skill,
    report_skill,
    standard_steps,
)

from tsutae import db
from tsutae.config import now
from tsutae.dataset import to_courses, to_entries
from tsutae.masking import GENERIC_MASK, RULE_UNKNOWN_BEFORE_HONORIFIC
from tsutae.pipeline.inputs import prepare_input
from tsutae.schemas import DoctorMask, EntryCreate, TextSpan

DEMO = "P-DEMO0001"
SUSPECT = 38
RAW = "磯鷲さんにもらった漢方をのんでみた。おなかがあったかい感じ"


def _runner(masks: dict[int, DoctorMask] | None = None) -> FakeRunner:
    """デモ患者の正解ラベルどおりに emit_* する runner（医師の伏せ字を入れた番号で）。"""
    patient, _labels = load_case("demo_patient")
    prepared = prepare_input(
        courses=to_courses(patient),
        entries=to_entries(patient),
        regimen_skill=regimen_skill(patient.regimen),
        report_skill=report_skill(),
        visit_date=patient.visit_date,
        doctor_masks=masks,
    )
    timeline, report = label_payloads("demo_patient", prepared)
    return FakeRunner(standard_steps(timeline, report))


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        assert DEMO in seed_synthetic(c.app)
        login_doctor(c)
        yield c


def _use(client: TestClient, runner: Any) -> None:
    client.app.state.runner_factory = RunnerFactory(runner)


def _ready_visit(client: TestClient) -> int:
    """デモ患者の受付（AI の結果で ready。記録38が未処理）。"""
    _use(client, _runner())
    register(client, DEMO)
    assert client.post("/api/visit", json={"reception_no": "A-023"}).status_code == 200
    with db_conn(client.app) as conn:
        vid = int(db.list_visits(conn)[-1]["id"])
        visit = db.get_visit(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", False)
    return vid


def _check(client: TestClient, vid: int, spans: list[list[int]], entry=SUSPECT):
    body = {"entry_id": entry, "spans": [{"start": s, "end": e} for s, e in spans]}
    return client.post(f"/api/doctor/visits/{vid}/masks/check", json=body)


def _save(client: TestClient, vid: int, *items: dict[str, Any]):
    return client.post(f"/api/doctor/visits/{vid}/masks", json={"entries": list(items)})


def _item(spans=((0, 2),), send=True, confirmed=False, entry=SUSPECT):
    return {
        "entry_id": entry,
        "send": send,
        "spans": [{"start": s, "end": e} for s, e in spans],
        "confirmed_clear": confirmed,
    }


def _logs(client: TestClient, vid: int) -> list[dict[str, Any]]:
    with db_conn(client.app) as conn:
        return db.list_pipeline_logs(conn, "visit", vid)


# --- 確かめる ------------------------------------------------------------------


def test_check_returns_masked_text_and_remaining_suspects(client: TestClient) -> None:
    vid = _ready_visit(client)
    r = _check(client, vid, [])
    assert r.status_code == 200
    assert r.json() == {
        "entry_id": SUSPECT,
        "masked_text": RAW,
        "suspects": [{"start": 0, "end": 4, "rule": RULE_UNKNOWN_BEFORE_HONORIFIC}],
        "reason": RULE_UNKNOWN_BEFORE_HONORIFIC,
        "sendable": False,
        "confirmable": True,
    }
    clean = _check(client, vid, [[0, 2]]).json()
    assert clean["masked_text"] == GENERIC_MASK + RAW[2:]
    assert (clean["suspects"], clean["sendable"]) == ([], True)


def test_check_does_not_save(client: TestClient) -> None:
    vid = _ready_visit(client)
    assert _check(client, vid, [[0, 2]]).status_code == 200
    with db_conn(client.app) as conn:
        assert db.list_doctor_masks(conn, vid) == {}


@pytest.mark.parametrize(
    "spans", [[[0, 999]], [[3, 2]], [[0, 3], [2, 4]], [[5, 7], [0, 2]]]
)
def test_check_rejects_bad_spans(client: TestClient, spans) -> None:
    vid = _ready_visit(client)
    r = _check(client, vid, spans)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_spans"}


def test_check_refuses_entry_not_in_unprocessed(client: TestClient) -> None:
    vid = _ready_visit(client)
    r = _check(client, vid, [], entry=1)
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_entry"}


def test_check_needs_json_and_login(client: TestClient) -> None:
    vid = _ready_visit(client)
    r = client.post(
        f"/api/doctor/visits/{vid}/masks/check",
        content="{}",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 415
    client.cookies.clear()
    assert _check(client, vid, []).status_code == 401


# --- 保存 ---------------------------------------------------------------------


def test_save_and_show_doctor_mask_in_unprocessed(client: TestClient) -> None:
    vid = _ready_visit(client)
    before = client.get(f"/api/doctor/visits/{vid}/unprocessed").json()
    assert before["entries"][0]["doctor_mask"] is None
    r = _save(client, vid, _item())
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sendable": 1}
    after = client.get(f"/api/doctor/visits/{vid}/unprocessed").json()
    assert after["entries"][0]["doctor_mask"] == {
        "spans": [{"start": 0, "end": 2}],
        "confirmed_clear": False,
    }
    # 生の記録は変わらない
    assert after["entries"][0]["text"] == RAW


def test_save_logs_without_text(client: TestClient) -> None:
    vid = _ready_visit(client)
    assert _save(client, vid, _item(spans=(), confirmed=True)).status_code == 200
    logs = [log for log in _logs(client, vid) if log["event"].startswith("doctor_")]
    assert [(log["event"], log["decision"]) for log in logs] == [
        ("doctor_mask_saved", f"entry:{SUSPECT}"),
        ("doctor_mask_confirmed", f"entry:{SUSPECT}"),
    ]
    assert _save(client, vid, _item(send=False)).status_code == 200
    removed = [
        log for log in _logs(client, vid) if log["event"] == "doctor_mask_removed"
    ]
    assert [log["decision"] for log in removed] == [f"entry:{SUSPECT}"]


def test_save_confirmed_keeps_exactly_the_remaining_suspect(client: TestClient) -> None:
    vid = _ready_visit(client)
    assert _save(client, vid, _item(spans=(), confirmed=True)).json() == {
        "ok": True,
        "sendable": 1,
    }
    with db_conn(client.app) as conn:
        assert db.list_doctor_masks(conn, vid) == {
            SUSPECT: DoctorMask(
                confirmed_clear=True, allowed=[TextSpan(start=0, end=4)]
            )
        }


def test_save_unconfirmed_suspect_is_kept_but_not_sendable(client: TestClient) -> None:
    vid = _ready_visit(client)
    assert _save(client, vid, _item(spans=())).json() == {"ok": True, "sendable": 0}


def test_save_send_false_removes(client: TestClient) -> None:
    vid = _ready_visit(client)
    _save(client, vid, _item())
    assert _save(client, vid, _item(send=False)).json() == {"ok": True, "sendable": 0}
    with db_conn(client.app) as conn:
        assert db.list_doctor_masks(conn, vid) == {}


def test_save_refuses_entry_not_in_unprocessed(client: TestClient) -> None:
    vid = _ready_visit(client)
    with db_conn(client.app) as conn:
        entry = db.add_entry(
            conn,
            DEMO,
            EntryCreate(free_text="受付はA-023でした"),
            now() - timedelta(hours=1),
            "regimen-folfox@1",
        )
    # 未処理の一覧に無い記録（受付の後に入れた記録）は断る
    r = _save(client, vid, _item(spans=(), confirmed=True, entry=entry.id))
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_entry"}


@pytest.mark.parametrize(
    "body",
    [
        {"entries": []},
        {"entries": [_item(), _item()]},
        {"entries": [{**_item(), "send": "yes"}]},
        {"entries": [{**_item(), "entry_id": True}]},
        {"entries": [{**_item(), "text": "書き換え"}]},
    ],
)
def test_save_rejects_bad_body(client: TestClient, body: dict[str, Any]) -> None:
    vid = _ready_visit(client)
    r = client.post(f"/api/doctor/visits/{vid}/masks", json=body)
    assert r.status_code == 422
    with db_conn(client.app) as conn:
        assert db.list_doctor_masks(conn, vid) == {}


def test_save_rejects_bad_spans(client: TestClient) -> None:
    vid = _ready_visit(client)
    r = _save(client, vid, _item(spans=((0, 999),)))
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_spans"}


def test_save_to_printed_visit_is_409(client: TestClient) -> None:
    vid = _ready_visit(client)
    assert client.post(f"/api/doctor/visits/{vid}/printed").status_code == 200
    r = _save(client, vid, _item())
    assert r.status_code == 409
    assert r.json() == {"error": "visit_closed"}
    assert _check(client, vid, []).status_code == 404


def test_save_to_generating_visit_is_409(client: TestClient) -> None:
    vid = _ready_visit(client)
    with db_conn(client.app) as conn:
        db.set_visit_status(conn, vid, "generating")
    r = _save(client, vid, _item())
    assert r.status_code == 409
    assert r.json() == {"error": "generating"}


def test_save_missing_visit_is_404(client: TestClient) -> None:
    r = _save(client, 9999, _item())
    assert r.status_code == 404


def test_save_cross_origin_is_403(client: TestClient) -> None:
    vid = _ready_visit(client)
    r = client.post(
        f"/api/doctor/visits/{vid}/masks",
        json={"entries": [_item()]},
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403


# --- 変換し直し ------------------------------------------------------------------


def test_regenerate_sends_doctor_masked_record(client: TestClient) -> None:
    vid = _ready_visit(client)
    masks = {SUSPECT: DoctorMask(spans=[TextSpan(start=0, end=2)])}
    # 先に保存しないと AI の結果の ready はやり直せない
    assert client.post(f"/api/doctor/visits/{vid}/regenerate").status_code == 409
    assert _save(client, vid, _item()).status_code == 200
    runner = _runner(masks)
    _use(client, runner)
    assert client.post(f"/api/doctor/visits/{vid}/regenerate").status_code == 200
    assert runner.calls == 1
    assert not runner.blocked
    assert GENERIC_MASK + "さんにもらった漢方" in runner.prompts[0]
    assert "磯鷲" not in runner.prompts[0]
    with db_conn(client.app) as conn:
        visit = db.get_visit(conn, vid)
        timeline = db.get_timeline(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", False)
    assert timeline is not None and timeline.unprocessed_entries == []
    events = [log["event"] for log in _logs(client, vid)]
    assert "doctor_masks_applied" in events
    assert client.get(f"/api/doctor/visits/{vid}/unprocessed").json()["entries"] == []


def test_regenerate_sends_confirmed_record_through_h1(client: TestClient) -> None:
    vid = _ready_visit(client)
    assert _save(client, vid, _item(spans=(), confirmed=True)).status_code == 200
    masks = {
        SUSPECT: DoctorMask(confirmed_clear=True, allowed=[TextSpan(start=0, end=4)])
    }
    runner = _runner(masks)
    _use(client, runner)
    assert client.post(f"/api/doctor/visits/{vid}/regenerate").status_code == 200
    assert not runner.blocked
    assert RAW in runner.prompts[0]
    with db_conn(client.app) as conn:
        visit = db.get_visit(conn, vid)
        timeline = db.get_timeline(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", False)
    assert timeline is not None and timeline.unprocessed_entries == []
    logs = _logs(client, vid)
    confirmed = [log for log in logs if log["event"] == "hook_h1_confirmed"]
    assert [(log["hook_name"], log["decision"]) for log in confirmed] == [
        ("H1", "confirmed:1")
    ]
    assert "doctor_confirmed_sent" in [log["event"] for log in logs]


def test_regenerate_without_ai_still_uses_doctor_mask_for_report(
    client: TestClient,
) -> None:
    """台本なし（AI 変換なし）でも、gate が同じ伏せ字で照合してレポートを作る。"""
    vid = _ready_visit(client)
    assert _save(client, vid, _item()).status_code == 200
    _use(client, FakeRunner())
    assert client.post(f"/api/doctor/visits/{vid}/regenerate").status_code == 200
    with db_conn(client.app) as conn:
        visit = db.get_visit(conn, vid)
        saved = db.get_report(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", True)
    assert saved is not None
    _html, data = saved
    assert all(item.kind != "unprocessed" for item in data.attention)

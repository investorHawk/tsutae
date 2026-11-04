"""医師 API: 受診・レポート・印刷済み・未処理（D6）・パイプライン（D5）（§8・§8b）。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import (
    add_entry,
    add_patient,
    api_client,
    db_conn,
    login_doctor,
    register,
)
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.config import jst_datetime, now
from tsutae.db.connection import dt_to_db
from tsutae.schemas import EntryCreate

C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
EVENT_KEYS = {
    "ts",
    "event",
    "hook_name",
    "agent_type",
    "tool_name",
    "decision",
    "duration_ms",
}


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        login_doctor(c)
        yield c


def _patient(client: TestClient) -> str:
    pid = add_patient(client.app, courses=C3)
    register(client, pid)
    return pid


def _visit(client: TestClient, reception_no: str = "A-023") -> dict[str, Any]:
    """患者の受付（POST /api/visit）で受診を作り、生成を済ませた行を返す。"""
    r = client.post("/api/visit", json={"reception_no": reception_no})
    assert r.status_code == 200
    with db_conn(client.app) as conn:
        return db.list_visits(conn)[-1]


def _ready_visit(client: TestClient) -> tuple[str, dict[str, Any]]:
    pid = _patient(client)
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    visit = _visit(client)
    assert visit["status"] == "ready"
    return pid, visit


def _bare_visit(client: TestClient, **kwargs: Any) -> int:
    """生成していない受診（status=generating）を直接作る。"""
    pid = kwargs.pop("pid", None) or add_patient(client.app, courses=C3)
    expires = kwargs.pop("expires_at", now() + timedelta(hours=24))
    with db_conn(client.app) as conn:
        return db.create_visit(conn, pid, "B-1", date(2026, 11, 9), expires, 3)


# ---------------------------------------------------------------------------
# 一覧
# ---------------------------------------------------------------------------


def test_list_visits(client: TestClient) -> None:
    pid, visit = _ready_visit(client)
    r = client.get("/api/doctor/visits")
    assert r.status_code == 200
    (item,) = r.json()["visits"]
    assert set(item) == {
        "id",
        "reception_no",
        "patient_id",
        "status",
        "fallback",
        "created_at",
        "expires_at",
        "unprocessed_count",
    }
    assert item["id"] == visit["id"]
    assert item["reception_no"] == "A-023"
    assert item["patient_id"] == pid
    assert item["status"] == "ready"
    assert item["fallback"] is True  # 台本なしの FakeRunner
    assert item["unprocessed_count"] == 0
    assert item["created_at"].endswith("+09:00")
    assert item["expires_at"].endswith("+09:00")


def test_list_visits_counts_unprocessed(client: TestClient) -> None:
    pid = _patient(client)
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    add_entry(client.app, pid, EntryCreate(free_text=f"紙に{pid}と書いてあった"))
    _visit(client)
    (item,) = client.get("/api/doctor/visits").json()["visits"]
    assert item["unprocessed_count"] == 1


def test_list_visits_purges_expired_first(client: TestClient) -> None:
    """期限切れは消してから一覧から外す（印刷待ちの一覧。仮名IDを出し続けない）。"""
    vid = _bare_visit(client, expires_at=now() - timedelta(minutes=1))
    live = _bare_visit(client)
    with db_conn(client.app) as conn:
        assert db.get_visit(conn, vid)["reception_no"] == "B-1"
    items = client.get("/api/doctor/visits").json()["visits"]
    assert [item["id"] for item in items] == [live]
    with db_conn(client.app) as conn:
        assert db.get_visit(conn, vid)["reception_no"] is None  # purge された


def test_list_visits_shows_only_open_statuses(client: TestClient) -> None:
    """一覧に出るのは受付番号のある generating・ready・failed だけ。"""
    generating = _bare_visit(client)
    failed = _bare_visit(client)
    _pid, ready = _ready_visit(client)
    printed = _bare_visit(client)
    with db_conn(client.app) as conn:
        db.set_visit_status(conn, failed, "failed")
        db.mark_printed(conn, printed)
    items = client.get("/api/doctor/visits").json()["visits"]
    assert [(i["id"], i["status"]) for i in items] == [
        (generating, "generating"),
        (failed, "failed"),
        (ready["id"], "ready"),
    ]
    assert all(i["reception_no"] is not None for i in items)


def test_list_visits_empty(client: TestClient) -> None:
    assert client.get("/api/doctor/visits").json() == {"visits": []}


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------


def test_report_html_with_headers(client: TestClient) -> None:
    _pid, visit = _ready_visit(client)
    r = client.get(f"/api/doctor/visits/{visit['id']}/report")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"] == CSP
    with db_conn(client.app) as conn:
        html, _data = db.get_report(conn, visit["id"])
    assert r.text == html
    assert "A-023" in r.text


def test_report_of_expired_visit_is_404(client: TestClient) -> None:
    # 生成が済んだ後に期限を過ぎた受診（期限切れの受診にはもう保存できないので、
    # ready にしてから expires_at を過去にする）
    c = client
    _pid, visit = _ready_visit(c)
    past = dt_to_db(now() - timedelta(minutes=1))
    with db_conn(c.app) as conn:
        conn.execute(
            "UPDATE visits SET expires_at = ? WHERE id = ?", (past, visit["id"])
        )
        conn.commit()
        assert db.get_report(conn, visit["id"]) is not None  # まだ消していない
        r = c.get(f"/api/doctor/visits/{visit['id']}/report")
        assert r.status_code == 404
        assert r.json() == {"error": "not_found"}
        with db_conn(c.app) as conn:
            assert db.get_report(conn, visit["id"]) is None


def test_report_of_generating_visit_is_404(client: TestClient) -> None:
    vid = _bare_visit(client)
    r = client.get(f"/api/doctor/visits/{vid}/report")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


def test_report_unknown_visit_is_404(client: TestClient) -> None:
    r = client.get("/api/doctor/visits/999/report")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


@pytest.mark.parametrize("vid", ["abc", "0", "-1", "1.5", "9" * 30])
@pytest.mark.parametrize(
    "template",
    [
        "/api/doctor/visits/{}/report",
        "/api/doctor/visits/{}/unprocessed",
        "/api/doctor/pipeline/{}/events",
    ],
)
def test_bad_visit_id_is_422(client: TestClient, template: str, vid: str) -> None:
    r = client.get(template.format(vid))
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


def test_bad_visit_id_printed_is_422(client: TestClient) -> None:
    r = client.post("/api/doctor/visits/abc/printed")
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


# ---------------------------------------------------------------------------
# 印刷済み
# ---------------------------------------------------------------------------


def test_printed_erases_report_and_reception_no(client: TestClient) -> None:
    pid = _patient(client)
    add_entry(client.app, pid, EntryCreate(free_text=f"紙に{pid}と書いてあった"))
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    visit = _visit(client)
    vid = visit["id"]
    assert client.get(f"/api/doctor/visits/{vid}/report").status_code == 200
    r = client.post(f"/api/doctor/visits/{vid}/printed")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    with db_conn(client.app) as conn:
        assert db.get_report(conn, vid) is None
        assert db.get_timeline(conn, vid) is None
        assert db.get_visit(conn, vid)["status"] == "printed"
    assert client.get(f"/api/doctor/visits/{vid}/report").status_code == 404
    assert client.get(f"/api/doctor/visits/{vid}/unprocessed").status_code == 404
    # 印刷済みは一覧から外れる（受付番号も仮名IDも出さない）
    assert client.get("/api/doctor/visits").json() == {"visits": []}
    # 2回目も ok（冪等）
    assert client.post(f"/api/doctor/visits/{vid}/printed").json() == {"ok": True}


def test_printed_unknown_visit_is_404(client: TestClient) -> None:
    r = client.post("/api/doctor/visits/999/printed")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


# ---------------------------------------------------------------------------
# 未処理（D6。原文を返す）
# ---------------------------------------------------------------------------


def test_unprocessed_returns_original_text(client: TestClient) -> None:
    pid = _patient(client)
    add_entry(client.app, pid, EntryCreate(free_text="おなかがゆるい日が続いた"))
    raw = f"紙に{pid}と書いてあった\n田中さんにも見せた"
    leaked = add_entry(client.app, pid, EntryCreate(free_text=raw))
    vid = _visit(client)["id"]
    r = client.get(f"/api/doctor/visits/{vid}/unprocessed")
    assert r.status_code == 200
    assert r.json() == {
        "entries": [
            {
                "entry_id": leaked,
                "record_date": "2026-11-09",
                "reason": "known_identifier",
                "text": raw,  # 伏せ字前の原文（○○さん にしていない）
                # 疑われた語（仮名ID）の原文の中の位置。田中は一次で伏せる辞書の姓
                "marks": [{"start": 2, "end": 2 + len(pid)}],
            }
        ]
    }


def test_unprocessed_empty_when_none(client: TestClient) -> None:
    _pid, visit = _ready_visit(client)
    r = client.get(f"/api/doctor/visits/{visit['id']}/unprocessed")
    assert r.json() == {"entries": []}


def test_unprocessed_of_generating_visit_is_empty(client: TestClient) -> None:
    vid = _bare_visit(client)
    assert client.get(f"/api/doctor/visits/{vid}/unprocessed").json() == {"entries": []}


def test_unprocessed_of_expired_visit_is_404(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path, report_ttl_hours=0) as c:
        login_doctor(c)
        pid = _patient(c)
        add_entry(c.app, pid, EntryCreate(free_text=f"紙に{pid}と書いてあった"))
        vid = _visit(c)["id"]
        r = c.get(f"/api/doctor/visits/{vid}/unprocessed")
        assert r.status_code == 404
        assert r.json() == {"error": "not_found"}


def test_unprocessed_unknown_visit_is_404(client: TestClient) -> None:
    r = client.get("/api/doctor/visits/999/unprocessed")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


# ---------------------------------------------------------------------------
# パイプラインのイベント（D5）
# ---------------------------------------------------------------------------


def test_pipeline_events(client: TestClient) -> None:
    _pid, visit = _ready_visit(client)
    vid = visit["id"]
    with db_conn(client.app) as conn:
        expected = db.list_pipeline_logs(conn, "visit", vid)
        # 別の受診・Skill 変更のログは混ざらない
        db.add_pipeline_log(conn, "skill_change", vid, "other_kind")
        db.add_pipeline_log(conn, "visit", vid + 100, "other_visit")
    assert expected  # 生成でログが書かれている
    r = client.get(f"/api/doctor/pipeline/{vid}/events")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    events = body["events"]
    assert [e["event"] for e in events] == [e["event"] for e in expected]
    assert all(set(e) == EVENT_KEYS for e in events)
    assert all(e["ts"].endswith("+09:00") for e in events)


def test_pipeline_events_while_generating(client: TestClient) -> None:
    vid = _bare_visit(client)
    with db_conn(client.app) as conn:
        db.add_pipeline_log(
            conn,
            "visit",
            vid,
            "tool_use",
            hook_name="H4",
            agent_type="term-mapper",
            tool_name="Agent",
            decision="allow",
            duration_ms=12,
            tokens_in=5,
            cost_usd=0.01,
            ts=jst_datetime(date(2026, 11, 9), 9, 30),
        )
    r = client.get(f"/api/doctor/pipeline/{vid}/events")
    assert r.json() == {
        "status": "generating",
        "events": [
            {
                "ts": "2026-11-09T09:30:00+09:00",
                "event": "tool_use",
                "hook_name": "H4",
                "agent_type": "term-mapper",
                "tool_name": "Agent",
                "decision": "allow",
                "duration_ms": 12,
            }
        ],
    }


def test_pipeline_events_unknown_visit_is_404(client: TestClient) -> None:
    r = client.get("/api/doctor/pipeline/999/events")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}

"""スマホ保存の通し（plan-device-records §2）。TestClient で、Claude は呼ばない。

撮影の DB（`seed_demo --device-records`。患者・コース・印だけ）→ 見本の記録を端末へ →
受付で送る → 変換 → D2・D6 → 印刷済みで DB の記録が消える。印と受診日は残る。
変換の入力は、記録をサーバーに置いた今までの形と同じになる。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from api_helpers import (
    api_client,
    db_conn,
    load_seed_module,
    login_doctor,
    register,
)
from e2e_scripts import copy_skills_home, demo_runner, set_runner
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner

DEMO = "P-DEMO0001"
RECEPTION = "A-023"


@contextmanager
def _client(
    tmp_path: Path, *, device_records: bool, runner: Any = None, **overrides: Any
) -> Iterator[TestClient]:
    home = copy_skills_home(tmp_path)
    with api_client(
        tmp_path,
        runner=runner,
        skills_dir=home / ".claude" / "skills",
        demo_tools=True,
        **overrides,
    ) as client:
        with db_conn(client.app) as conn:
            load_seed_module().seed(
                conn,
                skills_dir=client.app.state.settings.skills_dir,
                device_records=device_records,
            )
        assert register(client, DEMO).status_code == 200
        yield client


def _to_send(client: TestClient) -> list[dict[str, Any]]:
    """画面と同じように、端末の記録のうち範囲内を送る形にする（pid と文の写しを外す）。"""
    window = client.get(f"/api/patient/{DEMO}/visit-window").json()
    device = client.get(f"/api/patient/{DEMO}/demo-entries").json()["entries"]
    return [
        {
            **{k: v for k, v in e.items() if k != "pid"},
            "answers": [
                {k: v for k, v in a.items() if k != "question_text"}
                for a in e["answers"]
            ],
        }
        for e in device
        if window["start"] <= e["record_date"] <= window["end"]
    ]


def _send(client: TestClient, entries: list[dict[str, Any]]) -> None:
    body = {"reception_no": RECEPTION, "entries": entries}
    r = client.post("/api/visit", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "message_key": "visit.done"}


def _doctor_patient(client: TestClient) -> dict[str, Any]:
    patients = client.get("/api/doctor/patients").json()["patients"]
    return next(p for p in patients if p["id"] == DEMO)


def _d2_total(client: TestClient) -> int:
    return client.get(f"/api/doctor/patients/{DEMO}/entries").json()["total"]


def _visit_row(client: TestClient) -> dict[str, Any]:
    (visit,) = client.get(f"/api/doctor/patients/{DEMO}/visits").json()["visits"]
    return visit


def _table_counts(client: TestClient) -> dict[str, int]:
    with db_conn(client.app) as conn:
        return {
            t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
            for t in ("closed_answers", "free_texts", "doctor_masks")
        }


def _ids(client: TestClient) -> list[str | None]:
    with db_conn(client.app) as conn:
        rows = conn.execute(
            "SELECT client_entry_id FROM entries WHERE patient_id = ?", (DEMO,)
        ).fetchall()
    return [r["client_entry_id"] for r in rows]


def test_device_records_flow(tmp_path: Path, fixed_today: str) -> None:
    with _client(tmp_path, device_records=True) as client:
        login_doctor(client)
        # D1 は印から出て、D2 の記録はまだ無い
        before = _doctor_patient(client)
        assert before["last_record_date"] == "2026-11-08"
        assert before["days_since_last_record"] == 1
        assert before["record_stale"] is False
        assert _d2_total(client) == 0

        entries = _to_send(client)
        assert entries
        assert {e["client_entry_id"].split("-")[0] for e in entries} == {"demo"}
        _send(client, entries)  # 台本なしの runner なので AI 変換なしの結果になる
        assert _d2_total(client) == len(entries)
        visit = _visit_row(client)
        assert visit["fallback"] is True

        # 医師の「AI でもう一度変換」で、受け取った記録から AI の結果を作る
        set_runner(client, demo_runner(client, reception_no=RECEPTION))
        r = client.post(f"/api/doctor/visits/{visit['id']}/regenerate")
        assert r.status_code == 200, r.text
        visit = _visit_row(client)
        assert visit["status"] == "ready" and visit["fallback"] is False
        assert visit["unprocessed_count"] == 1
        unprocessed = client.get(f"/api/doctor/visits/{visit['id']}/unprocessed").json()
        (held,) = unprocessed["entries"]
        assert "磯鷲" in held["text"]  # D6 は原文を出す（受付から印刷まで置かれる）
        assert client.get(f"/api/doctor/visits/{visit['id']}/report").status_code == 200

        # 送り直しても増えない
        _send(client, entries)
        assert _d2_total(client) == len(entries)

        # 印刷済みで受け取った記録が消える。印・D1・受診日は残る
        r = client.post(f"/api/doctor/visits/{visit['id']}/printed")
        assert r.status_code == 200, r.text
        assert _ids(client) == []
        assert _table_counts(client) == {
            "closed_answers": 0,
            "free_texts": 0,
            "doctor_masks": 0,
        }
        assert _d2_total(client) == 0
        assert _doctor_patient(client)["last_record_date"] == "2026-11-08"
        days = client.get(f"/api/patient/{DEMO}/visit-days").json()["visits"]
        assert [d["visit_date"] for d in days] == ["2026-11-09"]


def test_ttl_erases_received_entries(tmp_path: Path, fixed_today: str) -> None:
    """24時間の期限（ここでは 0 時間）でも、受け取った記録が消える。"""
    with _client(tmp_path, device_records=True, report_ttl_hours=0) as client:
        login_doctor(client)
        _send(client, _to_send(client))
        assert client.get("/api/doctor/visits").status_code == 200  # 掃除が走る
        assert _ids(client) == []
        assert _table_counts(client)["free_texts"] == 0
        assert _doctor_patient(client)["last_record_date"] == "2026-11-08"


def test_server_entries_stay_after_printing(tmp_path: Path, fixed_today: str) -> None:
    """既定の seed の記録（client_entry_id なし）は印刷で消えない（評価・デモの仕組み）。"""
    with _client(tmp_path, device_records=False) as client:
        login_doctor(client)
        before = len(_ids(client))
        _send(client, [])
        visit = _visit_row(client)
        assert client.post(f"/api/doctor/visits/{visit['id']}/printed").is_success
        assert len(_ids(client)) == before


def _prompt(tmp_path: Path, *, device_records: bool) -> str:
    runner = FakeRunner()
    with _client(tmp_path, device_records=device_records, runner=runner) as client:
        _send(client, _to_send(client) if device_records else [])
    assert runner.calls == 1
    (prompt,) = runner.prompts
    return prompt


def test_conversion_input_is_the_same_as_server_records(
    tmp_path: Path, fixed_today: str
) -> None:
    """Claude への入力は、記録がサーバーにあった今までの形と同じ（変換を変えない）。"""
    device = _prompt(tmp_path / "device", device_records=True)
    server = _prompt(tmp_path / "server", device_records=False)
    assert device == server


def test_received_entries_are_not_shown_to_the_patient(
    tmp_path: Path, fixed_today: str
) -> None:
    """受け取った記録は患者の API に戻らない（受診日と質問集だけ）。"""
    with _client(tmp_path, device_records=True) as client:
        _send(client, _to_send(client))
        for name in ("visit-days", "visit-window", "questions"):
            r = client.get(f"/api/patient/{DEMO}/{name}")
            assert r.status_code == 200
            assert "磯鷲" not in r.text
        days = client.get(f"/api/patient/{DEMO}/visit-days").json()["visits"]
        assert days[0]["visit_date"] == "2026-11-09"

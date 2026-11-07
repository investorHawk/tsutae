"""撮影の見本の通し（plan-device-records §5.10）。`TSUTAE_DEMO_TOOLS=1` と `seed --device-records`。

見本を何度入れても・何度送っても二重にならず、受付で届く記録の数も Claude への入力の記録の数も、
合成データ（JSON）から独立に数えた値と同じになる。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from api_helpers import (
    api_client,
    db_conn,
    load_seed_module,
    login_doctor,
    register,
)
from e2e_scripts import (
    copy_skills_home,
    expected_pipeline_input,
    prompt_input,
)
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner

from tsutae.config import SYNTHETIC_DIR

DEMO = "P-DEMO0001"
RECEPTION = "A-023"
WINDOW_START = date(2026, 10, 13)  # C2 の Day1
WINDOW_END = date(2026, 11, 9)  # 受診日


@contextmanager
def _demo_client(tmp_path: Path, runner: FakeRunner) -> Iterator[TestClient]:
    home = copy_skills_home(tmp_path)
    with api_client(
        tmp_path,
        runner=runner,
        skills_dir=home / ".claude" / "skills",
        demo_tools=True,
    ) as client:
        with db_conn(client.app) as conn:
            load_seed_module().seed(
                conn,
                skills_dir=client.app.state.settings.skills_dir,
                device_records=True,
            )
        assert register(client, DEMO).status_code == 200
        login_doctor(client)
        yield client


def _synthetic_in_window() -> int:
    """合成データの JSON から直接数える（`demo-entries`・`seed` を通さない）。"""
    raw = json.loads((SYNTHETIC_DIR / "demo_patient.json").read_text("utf-8"))
    days = [date.fromisoformat(e["recorded_at"][:10]) for e in raw["entries"]]
    return sum(WINDOW_START <= d <= WINDOW_END for d in days)


def _device_shape(entry: dict[str, Any]) -> dict[str, Any]:
    """端末の記録を受付の形に（frontend の toVisitEntry と同じ）。"""
    return {
        **{k: v for k, v in entry.items() if k != "pid"},
        "answers": [
            {k: v for k, v in a.items() if k != "question_text"}
            for a in entry["answers"]
        ],
    }


def _samples(client: TestClient) -> list[dict[str, Any]]:
    """「見本の記録を入れる」: 端末は client_entry_id で保存するので、ID で一意になる。"""
    r = client.get(f"/api/patient/{DEMO}/demo-entries")
    assert r.status_code == 200, r.text
    return list({e["client_entry_id"]: e for e in r.json()["entries"]}.values())


def _in_window(client: TestClient, device: list[dict[str, Any]]) -> list[dict]:
    window = client.get(f"/api/patient/{DEMO}/visit-window").json()
    return [
        _device_shape(e)
        for e in device
        if window["start"] <= e["record_date"] <= window["end"]
    ]


def _send(client: TestClient, entries: list[dict[str, Any]]) -> None:
    body = {"reception_no": RECEPTION, "entries": entries}
    r = client.post("/api/visit", json=body)
    assert r.status_code == 200, r.text


def _rows(client: TestClient) -> list[str | None]:
    with db_conn(client.app) as conn:
        rows = conn.execute("SELECT client_entry_id AS id FROM entries").fetchall()
    return [r["id"] for r in rows]


def test_samples_do_not_double_and_match_the_synthetic_data(
    tmp_path: Path, fixed_today: str
) -> None:
    runner = FakeRunner()
    with _demo_client(tmp_path, runner) as client:
        assert _rows(client) == []  # 撮影の DB には記録が無い（印だけ）

        device = _samples(client) + _samples(client)  # 押し直し
        assert len({e["client_entry_id"] for e in device}) == len(device) / 2
        entries = _in_window(client, _samples(client))
        assert len(entries) == _synthetic_in_window()

        _send(client, entries)
        _send(client, entries)  # 送り直し
        rows = _rows(client)
        assert len(rows) == _synthetic_in_window()
        assert len(set(rows)) == len(rows)
        assert all(r is not None and r.startswith("demo-") for r in rows)
        total = client.get(f"/api/doctor/patients/{DEMO}/entries").json()["total"]
        assert total == _synthetic_in_window()

        questions = client.get(f"/api/patient/{DEMO}/questions").json()["questions"]

        (visit,) = client.get("/api/doctor/visits").json()["visits"]
        assert visit["status"] == "ready"
        assert client.post(f"/api/doctor/visits/{visit['id']}/printed").is_success
        assert _rows(client) == []

    # 変換の入力は、記録をサーバーに置いていたときの合成データと、数も中身も同じ
    assert runner.calls == 1
    (prompt,) = runner.prompts
    sent = prompt_input(prompt)
    expected = expected_pipeline_input([], questions)
    assert len(sent["entries"]) == len(expected["entries"])
    assert sent == expected


def test_a_record_made_today_is_added_to_the_samples_once(
    tmp_path: Path, fixed_today: str
) -> None:
    """見本を入れた端末で今日も記録すれば、受付の入力は合成データ + 1 件。"""
    runner = FakeRunner()
    with _demo_client(tmp_path, runner) as client:
        url = f"/api/patient/{DEMO}"
        version = client.get(f"{url}/questions").json()["skill_version"]
        mark = client.post(f"{url}/record-marks").json()
        today_body = {
            "by_proxy": False,
            "answers": [
                {"question_key": "diarrhea", "value": "present", "temperature": None}
            ],
            "free_text": None,
        }
        added = {
            "client_entry_id": "33333333-3333-4333-8333-333333333333",
            "recorded_at": mark["recorded_at"],
            "record_date": mark["record_date"],
            "kind": "answers",
            "skill_version": version,
            **today_body,
        }
        entries = [*_in_window(client, _samples(client)), added]
        _send(client, entries)
        _send(client, entries)
        assert len(_rows(client)) == _synthetic_in_window() + 1
        questions = client.get(f"{url}/questions").json()["questions"]
    (prompt,) = runner.prompts
    assert prompt_input(prompt) == expected_pipeline_input([today_body], questions)

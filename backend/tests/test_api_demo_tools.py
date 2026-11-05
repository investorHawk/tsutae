"""撮影用の見本（plan-device-records §5.10）。

`TSUTAE_DEMO_TOOLS=1` のときだけ、デモ患者にだけ合成データの記録を `demo-<seq>` の ID で返す。
環境変数が無ければ、経路は 404、画面が読む真偽は false で、どこにも出ない。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from api_helpers import (
    add_patient,
    api_client,
    db_conn,
    load_seed_module,
    make_settings,
    register,
    seed_synthetic,
    set_patient_cookie,
)
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.config import SYNTHETIC_DIR, get_settings
from tsutae.synthetic import load_patient

DEMO = "P-DEMO0001"
C1 = [(1, date(2026, 10, 27))]
ENTRY_KEYS = {
    "pid",
    "client_entry_id",
    "recorded_at",
    "record_date",
    "kind",
    "by_proxy",
    "skill_version",
    "answers",
    "free_text",
}


@pytest.fixture
def on(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path, demo_tools=True) as c:
        seed_synthetic(c.app)
        yield c


@pytest.fixture
def off(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        seed_synthetic(c.app)
        yield c


def _entries(client: TestClient, pid: str = DEMO) -> Any:
    return client.get(f"/api/patient/{pid}/demo-entries")


def _config(client: TestClient, pid: str = DEMO) -> Any:
    return client.get(f"/api/patient/{pid}/demo-config")


# ---------------------------------------------------------------------------
# 環境変数
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("", False), ("0", False), ("true", False), ("1", True)],
)
def test_setting_is_on_only_with_one(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    monkeypatch.delenv("TSUTAE_DEMO_TOOLS", raising=False)
    if value is not None:
        monkeypatch.setenv("TSUTAE_DEMO_TOOLS", value)
    assert get_settings().demo_tools is expected


def test_test_settings_do_not_follow_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TSUTAE_DEMO_TOOLS", "1")
    assert make_settings(tmp_path).demo_tools is False


# ---------------------------------------------------------------------------
# 無いとき: どこにも出ない
# ---------------------------------------------------------------------------


def test_off_entries_is_404(off: TestClient) -> None:
    assert register(off, DEMO).status_code == 200
    r = _entries(off)
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


def test_off_entries_is_404_without_cookie(off: TestClient) -> None:
    """有る無しを Cookie で探れないよう、入口の検査より先に 404。"""
    assert _entries(off).status_code == 404


def test_off_config_is_false(off: TestClient) -> None:
    assert register(off, DEMO).status_code == 200
    r = _config(off)
    assert r.status_code == 200
    assert r.json() == {"demo_tools": False}


def test_off_nothing_in_other_responses(off: TestClient) -> None:
    assert register(off, DEMO).status_code == 200
    for path in (
        "/api/patient/strings",
        "/api/patient/push-config",
        f"/api/patient/{DEMO}/questions",
        f"/api/patient/{DEMO}/visit-days",
        f"/api/patient/{DEMO}/visit-window",
    ):
        assert "demo-" not in off.get(path).text, path


# ---------------------------------------------------------------------------
# あるとき
# ---------------------------------------------------------------------------


def test_on_config_is_true_for_the_demo_patient_only(on: TestClient) -> None:
    assert register(on, DEMO).status_code == 200
    assert _config(on).json() == {"demo_tools": True}
    other = add_patient(on.app, courses=C1)
    assert register(on, other).status_code == 200
    assert _config(on, other).json() == {"demo_tools": False}


def test_on_config_needs_the_cookie_of_the_patient(on: TestClient) -> None:
    assert _config(on).status_code == 401
    other = add_patient(on.app, courses=C1)
    assert register(on, other).status_code == 200
    assert _config(on).status_code == 403


def test_on_entries_are_not_for_other_patients(on: TestClient) -> None:
    other = add_patient(on.app, courses=C1)
    assert register(on, other).status_code == 200
    r = _entries(on, other)
    assert r.status_code == 404
    assert _entries(on).status_code == 403  # デモ患者の経路を他の Cookie で読めない


def test_on_entries_need_a_cookie(on: TestClient) -> None:
    assert _entries(on).status_code == 401


def test_on_entries_unknown_patient_with_cookie_is_404(on: TestClient) -> None:
    set_patient_cookie(on, "P-ZZZZZZZZ")
    assert _entries(on, "P-ZZZZZZZZ").status_code == 404


def test_on_entries_come_from_the_synthetic_data(on: TestClient) -> None:
    assert register(on, DEMO).status_code == 200
    r = _entries(on)
    assert r.status_code == 200
    assert set(r.json()) == {"entries"}
    entries = r.json()["entries"]
    source = load_patient(SYNTHETIC_DIR / "demo_patient.json")
    assert [e["client_entry_id"] for e in entries] == [
        f"demo-{e.seq}" for e in sorted(source.entries, key=lambda x: x.recorded_at)
    ]
    assert all(set(e) == ENTRY_KEYS for e in entries)
    assert {e["pid"] for e in entries} == {DEMO}
    first = entries[0]
    assert first["recorded_at"].endswith("+09:00")
    assert first["record_date"] == first["recorded_at"][:10]
    assert first["kind"] == "answers"
    assert first["skill_version"] == "regimen-folfox@1"


def test_on_entries_have_copies_of_the_question_text(on: TestClient) -> None:
    assert register(on, DEMO).status_code == 200
    body = on.get(f"/api/patient/{DEMO}/questions").json()
    texts = {q["key"]: q["text"] for q in body["questions"]}
    entries = _entries(on).json()["entries"]
    answers = [a for e in entries for a in e["answers"]]
    assert answers
    for answer in answers:
        assert set(answer) == {"question_key", "value", "temperature", "question_text"}
        assert answer["question_text"] == texts[answer["question_key"]]


def test_on_entries_are_stable(on: TestClient) -> None:
    """押し直しても ID が同じなので増えない。"""
    assert register(on, DEMO).status_code == 200
    assert _entries(on).json() == _entries(on).json()


def test_on_entries_stop_at_today(
    on: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """今日より先の記録は端末に入れない（画面に未来の記録を出さない）。"""
    assert register(on, DEMO).status_code == 200
    every = _entries(on).json()["entries"]
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-01")
    some = _entries(on).json()["entries"]
    assert 0 < len(some) < len(every)
    assert max(e["record_date"] for e in some) <= "2026-11-01"


def test_on_entries_can_be_sent_at_the_visit(on: TestClient) -> None:
    """見本の記録を範囲内だけ受付で送れる（入れ直しても二重にならない）。"""
    assert register(on, DEMO).status_code == 200
    window = on.get(f"/api/patient/{DEMO}/visit-window").json()
    entries = [
        {
            **{k: v for k, v in e.items() if k != "pid"},
            "answers": [
                {k: v for k, v in a.items() if k != "question_text"}
                for a in e["answers"]
            ],
        }
        for e in _entries(on).json()["entries"]
        if window["start"] <= e["record_date"] <= window["end"]
    ]
    with db_conn(on.app) as conn:
        before = len(db.list_entries(conn, DEMO))
    body = {"reception_no": "A-023", "entries": entries}
    assert on.post("/api/visit", json=body).status_code == 200
    assert on.post("/api/visit", json=body).status_code == 200
    with db_conn(on.app) as conn:
        assert len(db.list_entries(conn, DEMO)) == before + len(entries)


# ---------------------------------------------------------------------------
# seed --device-records
# ---------------------------------------------------------------------------


def _counts(conn: Any) -> dict[str, int]:
    tables = ("patients", "courses", "entries", "record_marks", "free_texts")
    return {
        t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in tables
    }


def test_seed_device_records_has_marks_and_no_entries(tmp_path: Path) -> None:
    seed = load_seed_module()
    conn = db.connect(tmp_path / "device.db")
    try:
        added = seed.seed(
            conn, skills_dir=make_settings(tmp_path).skills_dir, device_records=True
        )
        counts = _counts(conn)
        assert DEMO in added
        assert counts["patients"] == 3
        assert counts["courses"] > 0
        assert counts["entries"] == 0
        assert counts["free_texts"] == 0
        source = load_patient(SYNTHETIC_DIR / "demo_patient.json")
        days = {e.recorded_at.date() for e in source.entries}
        rows = conn.execute(
            "SELECT record_date FROM record_marks WHERE patient_id = ?", (DEMO,)
        ).fetchall()
        assert {date.fromisoformat(r["record_date"]) for r in rows} == days
        assert db.last_record_dates(conn)[DEMO] == max(days)
    finally:
        conn.close()


def test_seed_default_keeps_entries(tmp_path: Path) -> None:
    seed = load_seed_module()
    conn = db.connect(tmp_path / "default.db")
    try:
        seed.seed(conn, skills_dir=make_settings(tmp_path).skills_dir)
        assert _counts(conn)["entries"] > 0
    finally:
        conn.close()


def test_seed_main_parses_the_flag(tmp_path: Path) -> None:
    seed = load_seed_module()
    path = tmp_path / "cli.db"
    args = ["--db", str(path), "--skills-dir", str(make_settings(tmp_path).skills_dir)]
    assert seed.main([*args, "--device-records"]) == 0
    conn = db.connect(path)
    try:
        assert _counts(conn)["entries"] == 0
        assert _counts(conn)["record_marks"] > 0
    finally:
        conn.close()

"""scripts/seed_demo.py（合成3人の投入。冪等で、DB を消さない）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from api_helpers import load_seed_module

from tsutae import db
from tsutae.config import SKILLS_DIR
from tsutae.synthetic import all_patients

seed_demo = load_seed_module()
EXPECTED = {p.patient_id: p for p, _labels in all_patients()}


def _counts(conn) -> dict[str, tuple[int, int]]:
    return {
        p["id"]: (
            len(db.list_courses(conn, p["id"])),
            len(db.list_entries(conn, p["id"])),
        )
        for p in db.list_patients(conn)
    }


def test_seed_inserts_three_patients(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        added = seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        assert sorted(added) == sorted(EXPECTED)
        counts = _counts(conn)
        for pid, patient in EXPECTED.items():
            assert counts[pid] == (len(patient.courses), len(patient.entries))
            assert db.get_patient(conn, pid)["regimen"] == patient.regimen
        demo = db.list_entries(conn, "P-DEMO0001")
        assert {e.skill_version for e in demo} == {"regimen-folfox@1"}
        assert db.latest_skill_version(conn, "regimen-folfox") is not None
        assert db.latest_skill_version(conn, "report-format-default") is not None
    finally:
        conn.close()


def test_seed_twice_does_not_add_patients(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        first = _counts(conn)
        assert seed_demo.seed(conn, skills_dir=SKILLS_DIR) == []
        assert _counts(conn) == first
        assert len(db.list_patients(conn)) == 3
    finally:
        conn.close()


def test_seed_keeps_existing_data(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        db.init_db(conn)
        other = db.create_patient(conn, "CAPOX")
        db.create_patient(conn, "FOLFOX", patient_id="P-DEMO0001")
        added = seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        assert "P-DEMO0001" not in added
        assert len(added) == 2
        counts = _counts(conn)
        assert counts["P-DEMO0001"] == (0, 0)  # 既にいる患者には触らない
        assert counts[other] == (0, 0)
        assert len(counts) == 4
    finally:
        conn.close()


def test_main_with_db_option_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nested" / "demo.db"
    assert seed_demo.main(["--db", str(path), "--skills-dir", str(SKILLS_DIR)]) == 0
    assert seed_demo.main(["--db", str(path), "--skills-dir", str(SKILLS_DIR)]) == 0
    out = capsys.readouterr().out
    assert "P-DEMO0001" in out
    conn = db.connect(path)
    try:
        assert len(db.list_patients(conn)) == 3
    finally:
        conn.close()


class _Boom(RuntimeError):
    pass


def _fail_on_nth_add_entry(monkeypatch: pytest.MonkeyPatch, nth: int) -> None:
    real = db.add_entry
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == nth:
            raise _Boom("わざと失敗")
        return real(*args, **kwargs)

    monkeypatch.setattr(db, "add_entry", flaky)


def test_failure_mid_patient_leaves_nothing_and_rerun_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "seed.db"
    conn = db.connect(path)
    try:
        _fail_on_nth_add_entry(monkeypatch, 3)  # デモ患者の3件目の記録で落とす
        with pytest.raises(_Boom):
            seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        monkeypatch.undo()
        assert conn.in_transaction is False
        assert db.list_patients(conn) == []  # 途中の患者を残さない
    finally:
        conn.close()
    other = db.connect(path)  # 別の接続から見ても残っていない
    try:
        assert other.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
        assert other.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0
        added = seed_demo.seed(other, skills_dir=SKILLS_DIR)
        assert sorted(added) == sorted(EXPECTED)
        counts = _counts(other)
        for pid, patient in EXPECTED.items():
            assert counts[pid] == (len(patient.courses), len(patient.entries))
    finally:
        other.close()


def test_failure_in_later_patient_keeps_earlier_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        order = [p.patient_id for p, _labels in all_patients()]
        first_entries = len(EXPECTED[order[0]].entries)
        _fail_on_nth_add_entry(monkeypatch, first_entries + 2)  # 2人目の途中
        with pytest.raises(_Boom):
            seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        monkeypatch.undo()
        counts = _counts(conn)
        assert set(counts) == {order[0]}  # 1人目は完全、2人目は無い
        first = EXPECTED[order[0]]
        assert counts[order[0]] == (len(first.courses), len(first.entries))
        assert sorted(seed_demo.seed(conn, skills_dir=SKILLS_DIR)) == sorted(order[1:])
        assert len(_counts(conn)) == 3
    finally:
        conn.close()


def test_autocommit_setting_is_restored(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        before = conn.autocommit
        seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        assert conn.autocommit == before
        assert conn.in_transaction is False
    finally:
        conn.close()


class _CommitFails:
    """COMMIT だけを失敗させる接続の包み（他は本物に渡す）。"""

    def __init__(self, conn) -> None:
        self._conn = conn

    def execute(self, sql: str, *args):
        if sql == "COMMIT":
            raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __setattr__(self, name: str, value) -> None:
        if name == "_conn":
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)


def test_atomic_rolls_back_when_commit_fails(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        db.init_db(conn)
        before = conn.autocommit
        wrapped = _CommitFails(conn)
        with pytest.raises(sqlite3.OperationalError), seed_demo._atomic(wrapped):
            conn.execute(
                "INSERT INTO patients (id, regimen, created_at) VALUES (?, ?, ?)",
                ("P-ZZZZ0001", "FOLFOX", "2026-11-09T09:00:00.000000+09:00"),
            )
        assert conn.in_transaction is False
        assert conn.autocommit == before
        assert db.list_patients(conn) == []
    finally:
        conn.close()


def test_atomic_refuses_open_transaction(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        db.init_db(conn)
        conn.execute(
            "INSERT INTO patients (id, regimen, created_at) VALUES (?, ?, ?)",
            ("P-ZZZZ0002", "FOLFOX", "2026-11-09T09:00:00.000000+09:00"),
        )
        assert conn.in_transaction
        with pytest.raises(RuntimeError), seed_demo._atomic(conn):
            pass
        conn.rollback()
    finally:
        conn.close()

"""scripts/seed_demo.py（合成3人の投入。冪等で、DB を消さない）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from api_helpers import load_seed_module

from tsutae import db
from tsutae.config import SKILLS_DIR
from tsutae.dataset import to_entry_create
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


def _fail_on_nth_entry(conn: sqlite3.Connection, nth: int) -> None:
    """この接続で、表に既に nth-1 件あるときの entries への INSERT を本物の DB の
    失敗にする（一時トリガ。seed_patient の中の1件ごとの INSERT で起きる）。"""
    conn.execute(
        "CREATE TEMP TRIGGER fail_entries BEFORE INSERT ON main.entries"
        f" WHEN (SELECT COUNT(*) FROM main.entries) >= {int(nth) - 1}"
        " BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )


def _stop_failing(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER temp.fail_entries")


def test_failure_mid_patient_leaves_nothing_and_rerun_completes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "seed.db"
    conn = db.connect(path)
    try:
        db.init_db(conn)
        _fail_on_nth_entry(conn, 3)  # デモ患者の3件目の記録で落とす
        with pytest.raises(sqlite3.Error):
            seed_demo.seed(conn, skills_dir=SKILLS_DIR)
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


def test_failure_in_later_patient_keeps_earlier_complete(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seed.db")
    try:
        db.init_db(conn)
        order = [p.patient_id for p, _labels in all_patients()]
        first_entries = len(EXPECTED[order[0]].entries)
        _fail_on_nth_entry(conn, first_entries + 2)  # 2人目の途中
        with pytest.raises(sqlite3.Error):
            seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        _stop_failing(conn)
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


def test_seed_demo_has_no_handwritten_transaction() -> None:
    """BEGIN/COMMIT の直書きをやめ、db.seed_patient に任せる。"""
    source = Path(seed_demo.__file__).read_text(encoding="utf-8")
    for word in ("BEGIN", "COMMIT", "ROLLBACK", "autocommit"):
        assert word not in source


def test_seed_keeps_seq_as_entry_id_on_empty_db(tmp_path: Path) -> None:
    """空の DB なら entries.id は合成データの seq と同じ（正解ラベルとの突き合わせ）。"""
    conn = db.connect(tmp_path / "seed.db")
    try:
        seed_demo.seed(conn, skills_dir=SKILLS_DIR)
        demo = EXPECTED["P-DEMO0001"]
        by_id = {e.id: e for e in db.list_entries(conn, "P-DEMO0001")}
        assert set(by_id) == {src.seq for src in demo.entries}
        for src in demo.entries:
            saved = by_id[src.seq]
            assert saved.recorded_at == src.recorded_at
            assert saved.free_text == to_entry_create(src).free_text
            assert saved.by_proxy == src.by_proxy
    finally:
        conn.close()


def test_seed_demo_uses_schema_types_only() -> None:
    """db の中の専用の型（旧 SeedEntry）を使わない。"""
    source = Path(seed_demo.__file__).read_text(encoding="utf-8")
    assert "SeedEntry" not in source

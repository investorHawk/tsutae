"""tsutae.skillchange の承認の排他・途中からの再開・一時ディレクトリの後始末。

- 承認・却下は Skill のディレクトリへの flock（プロセス間）で直列化する
- 状態の遷移は `status='pending'` の行だけに掛ける（条件付き UPDATE）
- 本体の書き込み後に落ちても、もう一度の承認で approved まで進められる
- 一時ディレクトリの削除の失敗はログ（短いコード）に残し、1回だけやり直す

skills_home は tmp_path に写したものを使う。editor は偽物。API は呼ばない。
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.schemas import RunStats
from tsutae.skillchange import (
    SkillChangeError,
    approve_change,
    reject_change,
    request_change,
    service,
    status_for,
)
from tsutae.skillchange import approve as approve_module
from tsutae.skillchange import lock as lock_module

NAME = "regimen-folfox"
OLD_Q = "text: 下痢はありましたか"
NEW_Q = "text: 下痢やお腹のゆるさはありましたか"
REQUEST = "下痢の質問をお腹のゆるさも含む文にして"

_HOLDER = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDONLY)
fcntl.flock(fd, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.readline()
"""


class Editor:
    """写しの SKILL.md の下痢の質問を書き換える。after があれば最後に呼ぶ。"""

    def __init__(self, transform=None, after=None) -> None:
        self.transform = transform or (lambda t: t.replace(OLD_Q, NEW_Q))
        self.after = after
        self.roots: list[Path] = []

    async def edit(self, work_root: Path, skill_name: str, request_text: str):
        self.roots.append(work_root)
        path = work_root / ".claude" / "skills" / skill_name / "SKILL.md"
        path.write_text(self.transform(path.read_text("utf-8")), "utf-8")
        if self.after is not None:
            self.after(work_root)
        return RunStats(duration_ms=1)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


@pytest.fixture
def skill_file(home: Path) -> Path:
    return home / ".claude" / "skills" / NAME / "SKILL.md"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "t.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = db.connect(db_path)
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def settings(home: Path):
    return dataclasses.replace(
        get_settings(), skills_dir=home / ".claude" / "skills", pipeline_timeout_s=5
    )


@pytest.fixture
def short_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lock_module, "LOCK_TIMEOUT_S", 0.3)


@pytest.fixture
def holder(skill_file: Path) -> Iterator[subprocess.Popen]:
    """別のプロセスが Skill のディレクトリの flock を握ったままにする。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(skill_file.parent)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "locked"
        yield proc
    finally:
        proc.communicate("\n", timeout=5)


async def _request(conn, home, settings, editor=None, name=NAME) -> int:
    return await request_change(
        conn,
        name,
        REQUEST,
        editor=editor or Editor(),
        settings=settings,
        skills_home=home,
    )


def _events(conn, cid) -> list[dict]:
    return db.list_pipeline_logs(conn, "skill_change", cid)


# ---------------------------------------------------------------------------
# プロセス間の排他
# ---------------------------------------------------------------------------


async def test_approve_waits_for_other_process_then_busy(
    conn, home, settings, skill_file, short_lock, holder
):
    cid = await _request(conn, home, settings)
    before = skill_file.read_bytes()
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "busy"
    assert skill_file.read_bytes() == before
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("pending", None)
    assert db.get_skill_version(conn, NAME, 2) is None


async def test_reject_also_takes_the_lock(conn, home, settings, short_lock, holder):
    cid = await _request(conn, home, settings)
    with pytest.raises(SkillChangeError) as info:
        reject_change(conn, cid, skills_home=home)
    assert info.value.code == "busy"
    assert db.get_skill_change(conn, cid)["status"] == "pending"


async def test_lock_is_released_after_approve(conn, home, settings, skill_file):
    cid = await _request(conn, home, settings)
    approve_change(conn, cid, skills_home=home)
    # 別のプロセスがすぐに取れる
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDONLY);"
            " fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)",
            str(skill_file.parent),
        ],
        timeout=10,
    )
    assert proc.returncode == 0


async def test_second_change_on_same_base_is_stale_and_keeps_winner(
    conn, db_path, home, settings, skill_file
):
    first = await _request(conn, home, settings)
    second = await _request(
        conn, home, settings, Editor(lambda t: t.replace("手足のしびれ", "手足の痺れ"))
    )
    other = db.connect(db_path)  # 別の接続（別の担当者の承認）
    try:
        assert approve_change(other, first, skills_home=home) == 2
    finally:
        other.close()
    winner = skill_file.read_bytes()
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, second, skills_home=home)
    assert info.value.code == "stale"
    assert skill_file.read_bytes() == winner
    assert db.get_skill_version(conn, NAME, 2)["content"] == winner.decode()


# ---------------------------------------------------------------------------
# 途中で落ちた承認の再開
# ---------------------------------------------------------------------------


class Crash(RuntimeError):
    pass


async def test_crash_after_version_saved_resumes(
    conn, home, settings, skill_file, monkeypatch
):
    cid = await _request(conn, home, settings)

    def crash(*_args, **_kwargs):
        raise Crash()

    with monkeypatch.context() as m:
        m.setattr(approve_module, "_mark_approved", crash)
        with pytest.raises(Crash):
            approve_change(conn, cid, skills_home=home)
    assert db.get_skill_change(conn, cid)["status"] == "pending"
    written = skill_file.read_text("utf-8")
    assert "\nversion: 2\n" in written
    assert db.get_skill_version(conn, NAME, 2)["content"] == written

    assert approve_change(conn, cid, skills_home=home) == 2
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["new_version"]) == ("approved", 2)
    assert skill_file.read_text("utf-8") == written
    names = [r["event"] for r in _events(conn, cid)]
    assert "skill_change_resume" in names
    assert names[-1] == "skill_change_approved"


async def test_crash_after_file_written_resumes(
    conn, home, settings, skill_file, monkeypatch
):
    cid = await _request(conn, home, settings)

    def crash(*_args, **_kwargs):
        raise Crash()

    with monkeypatch.context() as m:
        m.setattr(db, "save_skill_version", crash)
        with pytest.raises(Crash):
            approve_change(conn, cid, skills_home=home)
    assert "\nversion: 2\n" in skill_file.read_text("utf-8")
    assert db.get_skill_version(conn, NAME, 2) is None
    assert db.get_skill_change(conn, cid)["status"] == "pending"

    assert approve_change(conn, cid, skills_home=home) == 2
    saved = db.get_skill_version(conn, NAME, 2)
    assert saved["content"] == skill_file.read_text("utf-8")
    assert db.get_skill_change(conn, cid)["status"] == "approved"


async def test_same_text_from_other_approved_change_is_stale(
    conn, home, settings, skill_file
):
    first = await _request(conn, home, settings)
    twin = await _request(conn, home, settings)  # 同じ書き換え
    assert approve_change(conn, first, skills_home=home) == 2
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, twin, skills_home=home)
    assert info.value.code == "stale"
    assert db.get_skill_change(conn, twin)["status"] == "failed"


# ---------------------------------------------------------------------------
# ロールバックは自分の書いた内容のときだけ
# ---------------------------------------------------------------------------


async def test_rollback_when_version_save_fails(
    conn, home, settings, skill_file, monkeypatch
):
    cid = await _request(conn, home, settings)
    before = skill_file.read_bytes()

    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk")

    monkeypatch.setattr(db, "save_skill_version", fail)
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "version_conflict"
    assert skill_file.read_bytes() == before
    assert db.get_skill_change(conn, cid)["status"] == "failed"


async def test_no_rollback_over_someone_elses_write(
    conn, home, settings, skill_file, monkeypatch
):
    cid = await _request(conn, home, settings)
    other = skill_file.read_bytes() + b"\n# other writer\n"

    def overwrite_then_fail(*_args, **_kwargs):
        skill_file.write_bytes(other)
        raise ValueError("conflict")

    monkeypatch.setattr(db, "save_skill_version", overwrite_then_fail)
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "version_conflict"
    assert skill_file.read_bytes() == other
    logs = _events(conn, cid)
    assert any(r["event"] == "rollback_skipped" for r in logs)


async def test_version_conflict_checked_before_writing(
    conn, home, settings, skill_file, monkeypatch
):
    cid = await _request(conn, home, settings)
    db.save_skill_version(conn, NAME, 2, "別の内容", None)
    writes: list[Path] = []
    real = approve_module._write_atomic
    monkeypatch.setattr(
        approve_module, "_write_atomic", lambda p, d: (writes.append(p), real(p, d))
    )
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "version_conflict"
    assert writes == []


# ---------------------------------------------------------------------------
# 条件付きの状態遷移
# ---------------------------------------------------------------------------


async def test_decided_elsewhere_during_approve_is_not_pending(
    conn, db_path, home, settings, skill_file, monkeypatch
):
    cid = await _request(conn, home, settings)
    real = approve_module._write_atomic

    def write_and_reject(path, data):
        real(path, data)
        other = db.connect(db_path)
        try:
            db.update_skill_change(other, cid, status="rejected")
        finally:
            other.close()

    monkeypatch.setattr(approve_module, "_write_atomic", write_and_reject)
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "not_pending"
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("rejected", None)
    # 版は保存済みなので本体もそのまま（本体と skill_versions が食い違わない）
    assert db.get_skill_version(conn, NAME, 2)["content"] == skill_file.read_text(
        "utf-8"
    )
    assert any(r["event"] == "decided_elsewhere" for r in _events(conn, cid))


async def test_request_does_not_overwrite_decided_row(conn, home, settings):
    holder: dict[str, int] = {}

    def reject_during_edit(_root: Path) -> None:
        (change,) = db.list_skill_changes(conn)
        holder["id"] = change["id"]
        db.update_skill_change(conn, change["id"], status="rejected")

    cid = await _request(conn, home, settings, Editor(after=reject_during_edit))
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["diff"], change["new_text"]) == (
        "rejected",
        None,
        None,
    )


async def test_failed_request_does_not_overwrite_decided_row(conn, home, settings):
    def reject_during_edit(_root: Path) -> None:
        (change,) = db.list_skill_changes(conn)
        db.update_skill_change(conn, change["id"], status="rejected")

    cid = await _request(
        conn, home, settings, Editor(lambda t: t, after=reject_during_edit)
    )
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("rejected", None)


# ---------------------------------------------------------------------------
# 一時ディレクトリの後始末
# ---------------------------------------------------------------------------


async def test_readonly_dir_left_by_editor_is_still_removed(conn, home, settings):
    def make_readonly(root: Path) -> None:
        sub = root / "locked"
        sub.mkdir()
        (sub / "x.txt").write_text("x", "utf-8")
        sub.chmod(stat.S_IRUSR | stat.S_IXUSR)

    editor = Editor(after=make_readonly)
    cid = await _request(conn, home, settings, editor)
    assert not editor.roots[0].exists()
    assert db.get_skill_change(conn, cid)["status"] == "pending"
    assert not any(r["event"] == "temp_cleanup_failed" for r in _events(conn, cid))


async def test_rmtree_failure_once_is_retried(conn, home, settings, monkeypatch):
    real = shutil.rmtree
    calls: list[Path] = []

    def flaky(path, *args, **kwargs):
        calls.append(Path(path))
        if len(calls) == 1:
            raise PermissionError("busy")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(service.shutil, "rmtree", flaky)
    editor = Editor()
    cid = await _request(conn, home, settings, editor)
    assert len(calls) == 2
    assert not editor.roots[0].exists()
    assert not any(r["event"] == "temp_cleanup_failed" for r in _events(conn, cid))


async def test_rmtree_failure_is_logged_with_code_only(
    conn, home, settings, monkeypatch
):
    real = shutil.rmtree

    def broken(path, *args, **kwargs):
        raise PermissionError(f"cannot remove {path}")

    monkeypatch.setattr(service.shutil, "rmtree", broken)
    editor = Editor()
    cid = await _request(conn, home, settings, editor)
    monkeypatch.setattr(service.shutil, "rmtree", real)
    root = editor.roots[0]
    try:
        assert root.exists()
        change = db.get_skill_change(conn, cid)
        assert change["status"] == "pending"  # 後始末の失敗で結果は変えない
        (event,) = [
            r for r in _events(conn, cid) if r["event"] == "temp_cleanup_failed"
        ]
        assert event["decision"] == "error_type:PermissionError"
        assert str(root) not in repr(_events(conn, cid))
        assert root.name not in repr(_events(conn, cid))
    finally:
        real(root, ignore_errors=True)


async def test_rmtree_missing_dir_is_not_a_failure(conn, home, settings, monkeypatch):
    real = shutil.rmtree

    def vanish_then_missing(path, *args, **kwargs):
        real(path)
        raise FileNotFoundError(os.fspath(path))

    monkeypatch.setattr(service.shutil, "rmtree", vanish_then_missing)
    cid = await _request(conn, home, settings)
    assert not any(r["event"] == "temp_cleanup_failed" for r in _events(conn, cid))


# ---------------------------------------------------------------------------
# エラーコードと HTTP の対応（API の router が使う）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("invalid_name", 400),
        ("invalid_request", 400),
        ("unknown_skill", 404),
        ("not_found", 404),
        ("not_pending", 409),
        ("not_ready", 409),
        ("stale", 409),
        ("busy", 409),
        ("version_conflict", 409),
        ("write_error", 409),
        ("base_invalid", 500),
    ],
)
def test_status_for(code: str, status: int) -> None:
    assert status_for(code) == status

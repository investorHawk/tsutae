"""tsutae.skillchange.service（request_change・approve_change・reject_change）。

skills_home は tmp_path に backend/skills_home を写して使う（本物を書き換えない）。
editor は偽物（work_root の写しを書き換える）。API は呼ばない。
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import sqlite3
from collections.abc import Callable, Iterator
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
)
from tsutae.skills import load_skill

NAME = "regimen-folfox"
OLD_Q = "text: 下痢はありましたか"
NEW_Q = "text: 下痢やお腹のゆるさはありましたか"
REQUEST = "下痢の質問をお腹のゆるさも含む文にして"


def _change_question(text: str) -> str:
    assert OLD_Q in text
    return text.replace(OLD_Q, NEW_Q)


class FakeEditor:
    """写しの SKILL.md を transform で書き換える。呼ばれた時の様子を残す。"""

    def __init__(
        self,
        transform: Callable[[str], str] = _change_question,
        *,
        raises: BaseException | None = None,
        delay: float = 0.0,
        watch: Path | None = None,
    ) -> None:
        self.transform = transform
        self.raises = raises
        self.delay = delay
        self.watch = watch
        self.calls: list[tuple[Path, str, str]] = []
        self.files: list[str] = []
        self.watched: bytes | None = None

    async def edit(
        self, work_root: Path, skill_name: str, request_text: str
    ) -> RunStats:
        self.calls.append((work_root, skill_name, request_text))
        self.files = sorted(
            str(p.relative_to(work_root)) for p in work_root.rglob("*") if p.is_file()
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        path = work_root / ".claude" / "skills" / skill_name / "SKILL.md"
        path.write_text(self.transform(path.read_text("utf-8")), "utf-8")
        if self.watch is not None:
            self.watched = self.watch.read_bytes()
        return RunStats(duration_ms=10, num_turns=2, tokens_in=5, tokens_out=3)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


@pytest.fixture
def skill_file(home: Path) -> Path:
    return home / ".claude" / "skills" / NAME / "SKILL.md"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def settings(home: Path):
    return dataclasses.replace(
        get_settings(), skills_dir=home / ".claude" / "skills", pipeline_timeout_s=5
    )


async def _request(conn, home, settings, editor=None, text=REQUEST, name=NAME) -> int:
    return await request_change(
        conn,
        name,
        text,
        editor=editor or FakeEditor(),
        settings=settings,
        skills_home=home,
    )


# ---------------------------------------------------------------------------
# request_change
# ---------------------------------------------------------------------------


async def test_request_makes_pending_with_unified_diff(
    conn, home, settings, skill_file
):
    old = skill_file.read_text("utf-8")
    editor = FakeEditor()
    cid = await _request(conn, home, settings, editor)
    change = db.get_skill_change(conn, cid)
    assert change["status"] == "pending"
    assert change["error_code"] is None
    assert change["base_version"] == 1
    assert change["requested_text"] == REQUEST
    assert change["new_text"] == _change_question(old)
    diff = change["diff"]
    assert diff.startswith(f"--- a/{NAME}/SKILL.md\n+++ b/{NAME}/SKILL.md\n@@")
    assert f"\n-  - {{key: diarrhea, {OLD_Q}" in diff
    assert f"\n+  - {{key: diarrhea, {NEW_Q}" in diff
    assert editor.calls[0][1:] == (NAME, REQUEST)
    # 写しは1つの SKILL.md だけ
    assert editor.files == [f".claude/skills/{NAME}/SKILL.md"]


async def test_request_restores_version_bumped_by_agent(conn, home, settings):
    editor = FakeEditor(
        lambda t: _change_question(t).replace("version: 1\n", "version: 7\n")
    )
    cid = await _request(conn, home, settings, editor)
    change = db.get_skill_change(conn, cid)
    assert change["status"] == "pending"
    assert "version" not in change["diff"]
    assert "\nversion: 1\n" in change["new_text"]


async def test_request_only_version_bump_is_no_change(conn, home, settings):
    editor = FakeEditor(lambda t: t.replace("version: 1\n", "version: 2\n"))
    cid = await _request(conn, home, settings, editor)
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", "no_change")


@pytest.mark.parametrize(
    "transform, code",
    [
        (lambda t: t.replace("---", "", 2), "format"),  # frontmatter が壊れた
        (lambda t: t.replace("cycle_days: 14", "cycle_days: [14"), "format"),
        (lambda t: t.replace("cycle_days: 14", "cycle_days: two"), "schema"),
        (lambda t: t.replace(f"name: {NAME}", "name: regimen-x"), "name_mismatch"),
        (lambda t: t.replace("version: 1\n", ""), "schema"),
    ],
)
async def test_request_broken_result_is_failed(conn, home, settings, transform, code):
    cid = await _request(conn, home, settings, FakeEditor(transform))
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", code)
    assert change["diff"] is None and change["new_text"] is None


async def test_request_no_diff_is_failed(conn, home, settings):
    cid = await _request(conn, home, settings, FakeEditor(lambda t: t))
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", "no_change")


async def test_request_missing_output_is_failed(conn, home, settings):
    class Deleting(FakeEditor):
        async def edit(self, work_root, skill_name, request_text):
            (work_root / ".claude" / "skills" / skill_name / "SKILL.md").unlink()
            return RunStats()

    cid = await _request(conn, home, settings, Deleting())
    assert db.get_skill_change(conn, cid)["error_code"] == "missing_output"


async def test_original_untouched_during_and_after(conn, home, settings, skill_file):
    before = skill_file.read_bytes()
    stat = skill_file.stat()
    editor = FakeEditor(watch=skill_file)
    await _request(conn, home, settings, editor)
    assert editor.watched == before
    assert skill_file.read_bytes() == before
    assert skill_file.stat().st_mtime_ns == stat.st_mtime_ns
    assert sorted(p.name for p in skill_file.parent.iterdir()) == ["SKILL.md"]


@pytest.mark.parametrize(
    "editor",
    [
        FakeEditor(),
        FakeEditor(lambda t: t),
        FakeEditor(raises=RuntimeError("boom")),
    ],
)
async def test_temp_dir_is_removed(conn, home, settings, editor):
    await _request(conn, home, settings, editor)
    work_root = editor.calls[0][0]
    assert not work_root.exists()
    assert not work_root.is_relative_to(home)


async def test_editor_exception_is_failed(conn, home, settings):
    cid = await _request(conn, home, settings, FakeEditor(raises=RuntimeError("秘密")))
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", "editor_error")
    logs = db.list_pipeline_logs(conn, "skill_change", cid)
    assert any(r["decision"] == "error_type:RuntimeError" for r in logs)
    assert "秘密" not in repr(logs)


async def test_editor_timeout_is_failed(conn, home, settings):
    quick = dataclasses.replace(settings, pipeline_timeout_s=0.05)
    editor = FakeEditor(delay=1.0)
    cid = await _request(conn, home, quick, editor)
    assert db.get_skill_change(conn, cid)["error_code"] == "timeout"
    assert not editor.calls[0][0].exists()


async def test_editor_max_turns_is_failed(conn, home, settings):
    from claude_agent_sdk import ResultError

    err = ResultError("x", {"subtype": "error_max_turns"})
    cid = await _request(conn, home, settings, FakeEditor(raises=err))
    assert db.get_skill_change(conn, cid)["error_code"] == "max_turns"


async def test_cancel_marks_failed_and_cleans_up(conn, home, settings):
    editor = FakeEditor(delay=5.0)
    task = asyncio.ensure_future(_request(conn, home, settings, editor))
    while not editor.calls:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (change,) = db.list_skill_changes(conn)
    assert (change["status"], change["error_code"]) == ("failed", "cancelled")
    assert not editor.calls[0][0].exists()


async def test_request_with_name_and_honorific_is_h1_blocked(conn, home, settings):
    editor = FakeEditor()
    cid = await _request(
        conn, home, settings, editor, text="磯鷲さんの言い方に合わせて"
    )
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", "h1_blocked")
    assert editor.calls == []
    logs = db.list_pipeline_logs(conn, "skill_change", cid)
    assert "磯鷲" not in repr(logs)


@pytest.mark.parametrize(
    "name",
    [
        "../regimen-folfox",
        "regimen-folfox/../../x",
        "regimen-../../etc",
        "/etc/passwd",
        "Regimen-Folfox",
        "regimen-folfox\n",
        "",
        "skills",
        None,
    ],
)
async def test_request_rejects_bad_names(conn, home, settings, name):
    editor = FakeEditor()
    with pytest.raises(SkillChangeError) as info:
        await _request(conn, home, settings, editor, name=name)
    assert info.value.code == "invalid_name"
    assert editor.calls == []
    assert db.list_skill_changes(conn) == []


async def test_request_unknown_skill(conn, home, settings):
    with pytest.raises(SkillChangeError) as info:
        await _request(conn, home, settings, name="regimen-nothing")
    assert info.value.code == "unknown_skill"


@pytest.mark.parametrize("text", ["", "   \n", None, "あ" * 2001])
async def test_request_rejects_bad_text(conn, home, settings, text):
    with pytest.raises(SkillChangeError) as info:
        await _request(conn, home, settings, text=text)
    assert info.value.code == "invalid_request"
    assert db.list_skill_changes(conn) == []


async def test_request_logs_without_text(conn, home, settings):
    cid = await _request(conn, home, settings)
    logs = db.list_pipeline_logs(conn, "skill_change", cid)
    names = [r["event"] for r in logs]
    assert names[0] == "skill_change_request"
    assert "editor_done" in names
    assert names[-1] == "skill_change_pending"
    assert "下痢" not in repr(logs)


# ---------------------------------------------------------------------------
# approve_change / reject_change
# ---------------------------------------------------------------------------


async def test_approve_bumps_version_and_writes(conn, home, settings, skill_file):
    cid = await _request(conn, home, settings)
    new_version = approve_change(conn, cid, skills_home=home)
    assert new_version == 2
    text = skill_file.read_text("utf-8")
    assert NEW_Q in text and "\nversion: 2\n" in text
    assert load_skill(NAME, home / ".claude" / "skills").version == 2
    assert sorted(p.name for p in skill_file.parent.iterdir()) == ["SKILL.md"]
    saved = db.get_skill_version(conn, NAME, 2)
    assert saved["content"] == text
    texts = {q.key: q.text for q in saved["questions"]}
    assert texts["diarrhea"] == "下痢やお腹のゆるさはありましたか"
    change = db.get_skill_change(conn, cid)
    assert change["status"] == "approved"
    assert change["new_version"] == 2
    assert change["decided_at"] is not None
    events = [r["event"] for r in db.list_pipeline_logs(conn, "skill_change", cid)]
    assert events[-1] == "skill_change_approved"


async def test_approve_report_skill_saves_no_questions(conn, home, settings):
    name = "report-format-default"
    editor = FakeEditor(lambda t: t + "\n- 追記の一行\n")
    cid = await _request(conn, home, settings, editor, name=name)
    assert approve_change(conn, cid, skills_home=home) == 2
    assert db.get_skill_version(conn, name, 2)["questions"] is None


async def test_approve_stale_when_other_change_approved(
    conn, home, settings, skill_file
):
    first = await _request(conn, home, settings)
    second = await _request(
        conn,
        home,
        settings,
        FakeEditor(lambda t: t.replace("手足のしびれ", "手足のしびれ感")),
    )
    approve_change(conn, first, skills_home=home)
    after_first = skill_file.read_bytes()
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, second, skills_home=home)
    assert info.value.code == "stale"
    change = db.get_skill_change(conn, second)
    assert (change["status"], change["error_code"]) == ("failed", "stale")
    assert change["decided_at"] is not None
    assert skill_file.read_bytes() == after_first


async def test_approve_stale_when_file_changed_without_version(
    conn, home, settings, skill_file
):
    cid = await _request(conn, home, settings)
    skill_file.write_text(skill_file.read_text("utf-8") + "\n手で足した行\n", "utf-8")
    edited = skill_file.read_bytes()
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "stale"
    assert skill_file.read_bytes() == edited


async def test_approve_version_conflict_keeps_file(conn, home, settings, skill_file):
    cid = await _request(conn, home, settings)
    db.save_skill_version(conn, NAME, 2, "別の内容", None)
    before = skill_file.read_bytes()
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "version_conflict"
    assert skill_file.read_bytes() == before
    assert db.get_skill_change(conn, cid)["status"] == "failed"
    assert sorted(p.name for p in skill_file.parent.iterdir()) == ["SKILL.md"]


async def test_reject(conn, home, settings, skill_file):
    before = skill_file.read_bytes()
    cid = await _request(conn, home, settings)
    assert reject_change(conn, cid) is None
    change = db.get_skill_change(conn, cid)
    assert change["status"] == "rejected"
    assert change["decided_at"] is not None
    assert skill_file.read_bytes() == before


@pytest.mark.parametrize("decide", ["approve", "reject", "failed"])
async def test_only_pending_can_be_decided(conn, home, settings, decide):
    cid = await _request(conn, home, settings)
    if decide == "approve":
        approve_change(conn, cid, skills_home=home)
    elif decide == "reject":
        reject_change(conn, cid)
    else:
        cid = await _request(conn, home, settings, FakeEditor(lambda t: t))
    for call in (
        lambda: approve_change(conn, cid, skills_home=home),
        lambda: reject_change(conn, cid),
    ):
        with pytest.raises(SkillChangeError) as info:
            call()
        assert info.value.code == "not_pending"


def test_unknown_change_is_not_found(conn, home):
    for call in (
        lambda: approve_change(conn, 999, skills_home=home),
        lambda: reject_change(conn, 999),
    ):
        with pytest.raises(SkillChangeError) as info:
            call()
        assert info.value.code == "not_found"


def test_pending_without_new_text_is_not_ready(conn, home):
    cid = db.create_skill_change(conn, NAME, REQUEST, 1)
    with pytest.raises(SkillChangeError) as info:
        approve_change(conn, cid, skills_home=home)
    assert info.value.code == "not_ready"
    assert db.get_skill_change(conn, cid)["status"] == "pending"


def test_error_is_value_error_with_code() -> None:
    err = SkillChangeError("stale")
    assert isinstance(err, ValueError)
    assert err.code == "stale"


async def test_version_line_unreadable_by_approve_fails_at_request(
    conn, home, settings
):
    # YAML としては読めるが承認時に版を上げられない形は、依頼の時点で失敗にする
    editor = FakeEditor(
        lambda t: _change_question(t).replace("version: 1\n", '"version": 1\n')
    )
    cid = await _request(conn, home, settings, editor)
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", "version_line")


async def test_sdk_editor_logs_reach_db_through_request(conn, home, settings):
    from claude_agent_sdk import ResultMessage

    from tsutae.skillchange import SdkSkillEditor

    async def fake_query(*, prompt, options):
        for m in options.hooks["PreToolUse"]:
            if m.matcher is None:
                await m.hooks[0]({"tool_name": "Bash", "tool_input": {}}, None, None)
        yield ResultMessage(
            subtype="success",
            duration_ms=700,
            duration_api_ms=600,
            is_error=False,
            num_turns=3,
            session_id="s",
            total_cost_usd=0.05,
            usage={"input_tokens": 11, "output_tokens": 4},
        )

    editor = SdkSkillEditor(settings, query_fn=fake_query)
    cid = await _request(conn, home, settings, editor)
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", "no_change")
    logs = db.list_pipeline_logs(conn, "skill_change", cid)
    assert any(r["event"] == "hook_h4_deny" for r in logs)
    (done,) = [r for r in logs if r["event"] == "editor_done"]
    assert (done["duration_ms"], done["tokens_in"], done["tokens_out"]) == (700, 11, 4)
    assert done["cost_usd"] == pytest.approx(0.05)


def _failing_sdk_query(subtype: str | None, exc: Exception):
    from claude_agent_sdk import ResultMessage

    async def fake_query(*, prompt, options):
        if subtype is not None:
            yield ResultMessage(
                subtype=subtype,
                duration_ms=3000,
                duration_api_ms=2500,
                is_error=True,
                num_turns=12,
                session_id="s",
                total_cost_usd=0.42,
                usage={"input_tokens": 700, "output_tokens": 90},
            )
        raise exc

    return fake_query


@pytest.mark.parametrize(
    ("subtype", "code"),
    [
        ("error_max_budget_usd", "max_budget"),
        ("error_max_turns", "max_turns"),
        ("error_during_execution", "sdk_error"),
    ],
)
async def test_sdk_editor_failure_is_failed_with_code_and_cost(
    conn, home, settings, subtype, code
):
    from claude_agent_sdk import ResultError

    from tsutae.skillchange import SdkSkillEditor

    exc = ResultError(
        "Claude Code returned an error result: 秘密", {"subtype": subtype}
    )
    editor = SdkSkillEditor(settings, query_fn=_failing_sdk_query(subtype, exc))
    cid = await _request(conn, home, settings, editor)
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", code)
    logs = db.list_pipeline_logs(conn, "skill_change", cid)
    (failed,) = [r for r in logs if r["event"] == "editor_failed"]
    assert failed["decision"] == code
    assert (failed["duration_ms"], failed["tokens_in"], failed["tokens_out"]) == (
        3000,
        700,
        90,
    )
    assert failed["cost_usd"] == pytest.approx(0.42)
    # editor_error の型名は包む前の例外のもの
    (error,) = [r for r in logs if r["event"] == "editor_error"]
    assert error["decision"] == "error_type:ResultError"
    assert "秘密" not in repr(logs)


async def test_bare_budget_result_error_is_max_budget(conn, home, settings):
    from claude_agent_sdk import ResultError

    err = ResultError("x", {"subtype": "error_max_budget_usd"})
    cid = await _request(conn, home, settings, FakeEditor(raises=err))
    assert db.get_skill_change(conn, cid)["error_code"] == "max_budget"


# ---------------------------------------------------------------------------
# 行を作った後の一時ディレクトリの失敗（mkdtemp・mkdir・open の OSError）
# ---------------------------------------------------------------------------


def _fail_workdir(monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    from tsutae.skillchange import service as service_module

    def broken(*_args, **_kwargs):
        raise PermissionError("秘密のパス")

    if where == "mkdtemp":
        monkeypatch.setattr(service_module.tempfile, "mkdtemp", broken)
        return
    if where == "open":
        monkeypatch.setattr(service_module, "open", broken, raising=False)
        return
    real_mkdir = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if service_module._TEMP_PREFIX in str(self):
            broken()
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(service_module.Path, "mkdir", mkdir)


@pytest.mark.parametrize("where", ["mkdtemp", "mkdir", "open"])
async def test_workdir_os_error_is_failed_and_cleaned(
    conn, home, settings, skill_file, tmp_path, monkeypatch, where
):
    from tsutae.skillchange import service as service_module

    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr(service_module.tempfile, "tempdir", str(temp_root))
    before = skill_file.read_bytes()
    _fail_workdir(monkeypatch, where)
    editor = FakeEditor()
    cid = await _request(conn, home, settings, editor)
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("failed", "workdir_error")
    assert change["diff"] is None and change["new_text"] is None
    assert editor.calls == []  # 写しが無いまま editor を呼ばない
    assert list(temp_root.iterdir()) == []  # 作りかけの一時ディレクトリも消す
    assert skill_file.read_bytes() == before
    logs = db.list_pipeline_logs(conn, "skill_change", cid)
    assert ("workdir_error", "error_type:PermissionError") in [
        (r["event"], r["decision"]) for r in logs
    ]
    assert "秘密" not in repr(logs)

"""tsutae.pipeline.session_files（実行の後に ~/.claude/projects/ のセッションを消す）。

本物の home には触らない。projects の置き場所は tmp_path を渡すか、CLAUDE_CONFIG_DIR を
tmp_path に向ける。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultError,
    ResultMessage,
    SystemMessage,
)
from pipeline_fakes import prepare_case

from tsutae.pipeline.runner import RunFailedError, SdkRunner
from tsutae.pipeline.session_files import (
    projects_dir,
    query_cleaned,
    remove_session_files,
    session_id_of,
)
from tsutae.pipeline.tools import RunCollector

SID = "0b6f2a4e-3c1d-4e5f-9a7b-8c9d0e1f2a3b"
OTHER = "11111111-2222-4333-8444-555555555555"
ENC = "-Users-x-tsutae-backend-skills-home"


def _init(sid: str = SID) -> SystemMessage:
    return SystemMessage(subtype="init", data={"session_id": sid, "tools": []})


def _result(sid: str = SID) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id=sid,
        total_cost_usd=0.01,
    )


def _session_tree(root: Path, sid: str = SID, project: str = ENC) -> Path:
    """`<root>/<project>/<sid>/subagents/agent-1.meta.json` と `<sid>.jsonl` を作る。"""
    session = root / project / sid
    (session / "subagents").mkdir(parents=True)
    (session / "subagents" / "agent-1.meta.json").write_text("{}", encoding="utf-8")
    (root / project / f"{sid}.jsonl").write_text("{}\n", encoding="utf-8")
    return session


# ---------------------------------------------------------------------------
# session_id_of
# ---------------------------------------------------------------------------


def test_session_id_from_init_system_message() -> None:
    assert session_id_of(_init()) == SID


def test_session_id_from_message_attribute() -> None:
    assert session_id_of(_result()) == SID
    assert session_id_of(_result(SID.upper())) == SID.upper()


@pytest.mark.parametrize(
    "bad", ["", "s", "..", "../x", f"../{SID}", f"{SID}\n", f"{SID}/x", SID[:-1]]
)
def test_session_id_rejects_non_uuid(bad: str) -> None:
    assert session_id_of(_result(bad)) is None
    assert session_id_of(_init(bad)) is None


def test_session_id_ignores_other_objects() -> None:
    assert session_id_of(object()) is None
    assert session_id_of(SystemMessage(subtype="init", data={"tools": []})) is None
    assert session_id_of(SystemMessage(subtype="init", data={"session_id": 1})) is None


# ---------------------------------------------------------------------------
# projects_dir
# ---------------------------------------------------------------------------


def test_projects_dir_honours_claude_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert projects_dir() == tmp_path / "cfg" / "projects"


@pytest.mark.parametrize("value", [None, ""])
def test_projects_dir_defaults_to_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", value)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert projects_dir() == tmp_path / ".claude" / "projects"


# ---------------------------------------------------------------------------
# remove_session_files
# ---------------------------------------------------------------------------


def test_removes_session_dir_and_jsonl_only_for_given_ids(tmp_path: Path) -> None:
    session = _session_tree(tmp_path)
    kept = _session_tree(tmp_path, OTHER)
    other_project = _session_tree(tmp_path, OTHER, "-other-project")
    assert remove_session_files({SID}, tmp_path) == 2
    assert not session.exists()
    assert not (tmp_path / ENC / f"{SID}.jsonl").exists()
    assert (kept / "subagents" / "agent-1.meta.json").is_file()
    assert (tmp_path / ENC / f"{OTHER}.jsonl").is_file()
    assert (other_project / "subagents" / "agent-1.meta.json").is_file()


def test_removes_the_session_in_every_project(tmp_path: Path) -> None:
    _session_tree(tmp_path)
    _session_tree(tmp_path, SID, "-second")
    assert remove_session_files([SID], tmp_path) == 4
    assert [p.name for p in tmp_path.iterdir() if any(p.iterdir())] == []


@pytest.mark.parametrize("bad", ["../x", "..", "", ".", "x", f"../{ENC}"])
def test_ignores_non_uuid_ids(tmp_path: Path, bad: str) -> None:
    root = tmp_path / "projects"
    (root / ENC).mkdir(parents=True)
    victim = root / "x"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    assert remove_session_files({bad}, root) == 0
    assert (victim / "keep.txt").is_file()
    assert (root / ENC).is_dir()


def test_does_not_follow_a_symlinked_session_dir(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    (root / ENC).mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "precious.txt").write_text("keep", encoding="utf-8")
    (root / ENC / SID).symlink_to(target, target_is_directory=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("keep", encoding="utf-8")
    (root / ENC / f"{SID}.jsonl").symlink_to(outside)
    assert remove_session_files({SID}, root) == 0
    assert (target / "precious.txt").is_file()
    assert outside.is_file()


def test_does_not_follow_a_symlinked_project_dir(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    real = tmp_path / "real-project"
    session = _session_tree(tmp_path, SID, "real-project")
    (root / "linked").symlink_to(real, target_is_directory=True)
    assert remove_session_files({SID}, root) == 0
    assert session.is_dir()


def test_missing_root_or_no_ids_is_zero(tmp_path: Path) -> None:
    assert remove_session_files({SID}, tmp_path / "nope") == 0
    _session_tree(tmp_path)
    assert remove_session_files(set(), tmp_path) == 0
    assert (tmp_path / ENC / SID).is_dir()


def test_files_in_root_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")
    _session_tree(tmp_path)
    assert remove_session_files({SID}, tmp_path) == 2
    assert (tmp_path / "stray.txt").is_file()


def test_uses_claude_config_dir_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    session = _session_tree(tmp_path / "projects")
    assert remove_session_files({SID}) == 2
    assert not session.exists()


def test_errors_are_swallowed_and_logged_without_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _session_tree(tmp_path)

    def broken(*args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "denied", str(tmp_path))

    monkeypatch.setattr("tsutae.pipeline.session_files.shutil.rmtree", broken)
    assert remove_session_files({SID}, tmp_path) == 1  # .jsonl だけ消えた
    assert "PermissionError" in caplog.text
    assert str(tmp_path) not in caplog.text and SID not in caplog.text


# ---------------------------------------------------------------------------
# query_cleaned
# ---------------------------------------------------------------------------


def _query(messages: list[Any], events: list[str], *, hang: bool = False):
    async def fake_query(*, prompt: str, options: ClaudeAgentOptions):
        try:
            for message in messages:
                yield message
            if hang:
                await asyncio.sleep(3600)
        finally:
            events.append("closed")

    return fake_query


async def test_query_cleaned_closes_the_query_before_removing(tmp_path: Path) -> None:
    session = _session_tree(tmp_path)
    events: list[str] = []
    stream = query_cleaned(
        _query([_init(), _result()], events),
        prompt="p",
        options=ClaudeAgentOptions(),
        projects_root=tmp_path,
    )
    first = await stream.__anext__()
    assert session_id_of(first) == SID and session.is_dir()
    await stream.aclose()  # 途中で閉じても、元の query を閉じてから消す
    assert events == ["closed"]
    assert not session.exists()


# ---------------------------------------------------------------------------
# SdkRunner の後始末
# ---------------------------------------------------------------------------


def _collector() -> RunCollector:
    return RunCollector.from_prepared(prepare_case("demo_patient"))


async def test_runner_removes_session_files_after_success(tmp_path: Path) -> None:
    session = _session_tree(tmp_path)
    kept = _session_tree(tmp_path, OTHER)
    runner = SdkRunner(
        query_fn=_query([_init(), _result()], []), projects_root=tmp_path
    )
    stats = await runner.run("p", ClaudeAgentOptions(), _collector())
    assert stats.num_turns == 1
    assert not session.exists() and kept.is_dir()


async def test_runner_removes_session_files_on_sdk_error(tmp_path: Path) -> None:
    session = _session_tree(tmp_path)

    async def failing(*, prompt: str, options: ClaudeAgentOptions):
        yield _init()
        raise ResultError("max turns", {"subtype": "error_max_turns"})

    runner = SdkRunner(query_fn=failing, projects_root=tmp_path)
    with pytest.raises(RunFailedError):
        await runner.run("p", ClaudeAgentOptions(), _collector())
    assert not session.exists()


async def test_runner_removes_session_files_on_other_errors(tmp_path: Path) -> None:
    session = _session_tree(tmp_path)

    async def broken(*, prompt: str, options: ClaudeAgentOptions):
        yield _init()
        raise RuntimeError("bug")

    runner = SdkRunner(query_fn=broken, projects_root=tmp_path)
    with pytest.raises(RuntimeError):
        await runner.run("p", ClaudeAgentOptions(), _collector())
    assert not session.exists()


async def test_runner_removes_session_files_on_timeout(tmp_path: Path) -> None:
    session = _session_tree(tmp_path)
    events: list[str] = []
    runner = SdkRunner(
        query_fn=_query([_init()], events, hang=True), projects_root=tmp_path
    )
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            runner.run("p", ClaudeAgentOptions(), _collector()), 0.05
        )
    assert events == ["closed"]
    assert not session.exists()


async def test_runner_cancellation_still_propagates(tmp_path: Path) -> None:
    session = _session_tree(tmp_path)
    started = asyncio.Event()

    async def hanging(*, prompt: str, options: ClaudeAgentOptions):
        yield _init()
        started.set()
        await asyncio.sleep(3600)

    runner = SdkRunner(query_fn=hanging, projects_root=tmp_path)
    task = asyncio.create_task(runner.run("p", ClaudeAgentOptions(), _collector()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not session.exists()


async def test_runner_resolves_root_from_env_at_run_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = SdkRunner(query_fn=_query([_init(), _result()], []))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    session = _session_tree(tmp_path / "projects")
    await runner.run("p", ClaudeAgentOptions(), _collector())
    assert not session.exists()

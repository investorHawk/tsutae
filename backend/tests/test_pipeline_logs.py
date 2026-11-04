"""tsutae.pipeline.logs（文面を入れないログ。Hook の中で例外を出さない）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsutae.db import connect, init_db, list_pipeline_logs
from tsutae.pipeline.logs import INVALID, MemoryLogger, PipelineLogger, reason_code


def test_memory_logger_keeps_events_in_order() -> None:
    log = MemoryLogger()
    log.event("run_start")
    log.event("hook_h4_deny", hook_name="H4", tool_name="Bash", decision="deny")
    assert log.names() == ["run_start", "hook_h4_deny"]
    assert log.records[1] == {
        "event": "hook_h4_deny",
        "hook_name": "H4",
        "tool_name": "Bash",
        "decision": "deny",
    }
    assert log.find("hook_h4_deny") == [log.records[1]]


def test_text_fields_must_be_ascii_identifiers() -> None:
    log = MemoryLogger()
    log.event("tool_use", tool_name="下痢が3回", agent_type="a b", decision="x" * 101)
    assert log.records[0] == {
        "event": "tool_use",
        "tool_name": INVALID,
        "agent_type": INVALID,
        "decision": INVALID,
    }


def test_none_fields_are_left_out() -> None:
    log = MemoryLogger()
    log.event("subagent_stop", agent_type=None, duration_ms=None)
    assert log.records == [{"event": "subagent_stop"}]


def test_numbers_are_kept_only_when_valid() -> None:
    log = MemoryLogger()
    log.event("run_end", duration_ms=1200, tokens_in=-1, tokens_out=True, cost_usd=0.25)
    assert log.records == [{"event": "run_end", "duration_ms": 1200, "cost_usd": 0.25}]


def test_unknown_field_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        MemoryLogger().event("run_start", text="本文")


def test_event_name_must_be_identifier() -> None:
    with pytest.raises(ValueError):
        MemoryLogger().event("引用")


def test_reason_code_is_short_ascii() -> None:
    assert reason_code("deny", "events.2.source_quote") == "deny:events.2.source_quote"
    assert reason_code("block", "at_mark") == "block:at_mark"
    long = reason_code("deny", "x" * 300)
    assert len(long) == 100
    assert reason_code("deny", "下痢") == "deny:__"


def _conn(path: Path):
    conn = connect(path)
    init_db(conn)
    return conn


def test_pipeline_logger_writes_rows(tmp_db_path: Path) -> None:
    conn = _conn(tmp_db_path)
    log = PipelineLogger(conn, "visit", 7)
    log.event("run_start")
    log.event("hook_h2_deny", hook_name="H2", tool_name="引用", decision="deny")
    log.event("run_end", duration_ms=10, tokens_in=5, tokens_out=3, cost_usd=0.01)
    rows = list_pipeline_logs(conn, "visit", 7)
    assert [r["event"] for r in rows] == ["run_start", "hook_h2_deny", "run_end"]
    assert rows[1]["tool_name"] == INVALID
    assert rows[2]["tokens_in"] == 5 and rows[2]["cost_usd"] == 0.01
    assert log.failures == 0


def test_pipeline_logger_does_not_raise_when_db_fails(tmp_db_path: Path) -> None:
    conn = _conn(tmp_db_path)
    log = PipelineLogger(conn, "visit", 1)
    conn.close()
    log.event("run_start")  # 例外を出さない（Hook の中で呼ばれる）
    assert log.failures == 1


def test_pipeline_logger_rejects_bad_run_kind(tmp_db_path: Path) -> None:
    conn = _conn(tmp_db_path)
    with pytest.raises(ValueError):
        PipelineLogger(conn, "patient", 1)
    with pytest.raises(ValueError):
        PipelineLogger(conn, "visit", "1")  # type: ignore[arg-type]

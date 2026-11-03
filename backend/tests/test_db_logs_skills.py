"""パイプラインのログ（文面なし）と Skill の変更・版の保存。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from tsutae.config import JST
from tsutae.db import (
    NotFoundError,
    add_pipeline_log,
    connect,
    create_skill_change,
    get_skill_change,
    get_skill_version,
    init_db,
    latest_skill_version,
    list_pipeline_logs,
    list_skill_changes,
    save_skill_version,
    update_skill_change,
)
from tsutae.schemas import Question

TS = datetime(2026, 11, 9, 10, 0, tzinfo=JST)
QUESTIONS = [
    Question(
        key="numbness", text="手足のしびれはありましたか", answer_type="three_level"
    ),
    Question(key="fever", text="熱を測りましたか", answer_type="temperature"),
]


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


# --- pipeline_logs -----------------------------------------------------------


def test_add_and_list_pipeline_logs(conn: sqlite3.Connection) -> None:
    add_pipeline_log(conn, "visit", 1, "run.start", ts=TS)
    add_pipeline_log(
        conn,
        "visit",
        1,
        "hook.pre_tool_use",
        hook_name="H2",
        agent_type="main",
        tool_name="mcp__tsutae__emit_timeline",
        decision="allow",
        duration_ms=12,
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.01,
    )
    add_pipeline_log(conn, "visit", 2, "run.start")
    add_pipeline_log(conn, "skill_change", 1, "run.start")

    logs = list_pipeline_logs(conn, "visit", 1)
    assert [log["event"] for log in logs] == ["run.start", "hook.pre_tool_use"]
    assert logs[0]["ts"] == TS
    assert logs[0]["hook_name"] is None
    assert logs[1]["hook_name"] == "H2"
    assert logs[1]["tool_name"] == "mcp__tsutae__emit_timeline"
    assert logs[1]["decision"] == "allow"
    assert logs[1]["duration_ms"] == 12
    assert logs[1]["tokens_in"] == 100
    assert logs[1]["tokens_out"] == 50
    assert logs[1]["cost_usd"] == pytest.approx(0.01)
    assert logs[1]["ts"].utcoffset() is not None
    assert len(list_pipeline_logs(conn, "skill_change", 1)) == 1
    assert list_pipeline_logs(conn, "visit", 99) == []


@pytest.mark.parametrize("field", ["text", "message", "prompt", "content", "quote"])
def test_add_pipeline_log_rejects_text_fields(
    conn: sqlite3.Connection, field: str
) -> None:
    with pytest.raises(ValueError):
        add_pipeline_log(conn, "visit", 1, "e", **{field: "患者の文"})
    assert list_pipeline_logs(conn, "visit", 1) == []


def test_add_pipeline_log_rejects_unknown_run_kind(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        add_pipeline_log(conn, "report", 1, "e")


def test_add_pipeline_log_rejects_long_identifier(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        add_pipeline_log(conn, "visit", 1, "e", hook_name="x" * 201)
    with pytest.raises(ValueError):
        add_pipeline_log(conn, "visit", 1, "")


TEXT_COLUMNS = ("hook_name", "agent_type", "tool_name", "decision")
PATIENT_LIKE = [
    "おとといから下痢がひどく、相談した",
    "引用『お腹がずっとゆるい』が原文に一致しない",
    "x\nmulti\nline",
    "deny\n",
    "has space",
    "tab\tsep",
    "ｈ２",  # 全角
    "x" * 101,
    "",
]


@pytest.mark.parametrize("value", PATIENT_LIKE)
def test_add_pipeline_log_rejects_text_in_event(
    conn: sqlite3.Connection, value: str
) -> None:
    with pytest.raises(ValueError):
        add_pipeline_log(conn, "visit", 1, value)
    assert list_pipeline_logs(conn, "visit", 1) == []


@pytest.mark.parametrize("column", TEXT_COLUMNS)
@pytest.mark.parametrize("value", PATIENT_LIKE)
def test_add_pipeline_log_rejects_text_in_identifier_columns(
    conn: sqlite3.Connection, column: str, value: str
) -> None:
    with pytest.raises(ValueError):
        add_pipeline_log(conn, "visit", 1, "hook.pre_tool_use", **{column: value})
    assert list_pipeline_logs(conn, "visit", 1) == []


@pytest.mark.parametrize(
    "value",
    [
        "mcp__tsutae__emit_timeline",
        "date-normalizer",
        "hook.pre_tool_use",
        "unknown_before_honorific",
        "H2",
        "deny",
        "events.2.source_quote",
        "regimen-folfox@1",
        "skills/regimen-folfox:approve",
        "x" * 100,
    ],
)
def test_add_pipeline_log_accepts_identifiers(
    conn: sqlite3.Connection, value: str
) -> None:
    add_pipeline_log(
        conn,
        "visit",
        1,
        value,
        hook_name=value,
        agent_type=value,
        tool_name=value,
        decision=value,
    )
    (log,) = list_pipeline_logs(conn, "visit", 1)
    assert log["event"] == value
    assert all(log[column] == value for column in TEXT_COLUMNS)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("duration_ms", -5),
        ("tokens_in", -1),
        ("tokens_out", -1),
        ("cost_usd", -0.1),
        ("cost_usd", float("nan")),
        ("cost_usd", float("inf")),
        ("cost_usd", float("-inf")),
        ("duration_ms", "12"),
        ("duration_ms", 1.5),
        ("tokens_in", True),
        ("cost_usd", "0.1"),
    ],
)
def test_add_pipeline_log_rejects_bad_numbers(
    conn: sqlite3.Connection, column: str, value: object
) -> None:
    with pytest.raises(ValueError):
        add_pipeline_log(conn, "visit", 1, "run.end", **{column: value})
    assert list_pipeline_logs(conn, "visit", 1) == []


def test_add_pipeline_log_accepts_zero_numbers(conn: sqlite3.Connection) -> None:
    add_pipeline_log(
        conn,
        "visit",
        1,
        "run.end",
        duration_ms=0,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0,
    )
    (log,) = list_pipeline_logs(conn, "visit", 1)
    assert log["duration_ms"] == 0
    assert log["cost_usd"] == 0.0
    assert isinstance(log["cost_usd"], float)


# --- skill_changes -----------------------------------------------------------


def test_create_and_get_skill_change(conn: sqlite3.Connection, fixed_today) -> None:
    cid = create_skill_change(
        conn, "regimen-folfox", "手足症候群の質問を足して", base_version=1
    )
    change = get_skill_change(conn, cid)
    assert change is not None
    assert change["id"] == cid
    assert change["skill_name"] == "regimen-folfox"
    assert change["requested_text"] == "手足症候群の質問を足して"
    assert change["base_version"] == 1
    assert change["status"] == "pending"
    assert change["diff"] is None
    assert change["new_text"] is None
    assert change["new_version"] is None
    assert change["error_code"] is None
    assert change["decided_at"] is None
    assert change["created_at"].date().isoformat() == "2026-11-09"


def test_create_skill_change_with_diff(conn: sqlite3.Connection) -> None:
    cid = create_skill_change(
        conn,
        "report-format-default",
        "引用を10件まで",
        base_version=2,
        diff="-a\n+b",
        new_text="---\nname: x\n---\n",
    )
    change = get_skill_change(conn, cid)
    assert change["diff"] == "-a\n+b"
    assert change["new_text"] == "---\nname: x\n---\n"


def test_update_skill_change(conn: sqlite3.Connection) -> None:
    cid = create_skill_change(conn, "regimen-folfox", "依頼", base_version=1)
    update_skill_change(
        conn, cid, status="approved", new_version=2, decided_at=TS, diff="d"
    )
    change = get_skill_change(conn, cid)
    assert change["status"] == "approved"
    assert change["new_version"] == 2
    assert change["decided_at"] == TS
    assert change["diff"] == "d"
    update_skill_change(conn, cid, status="failed", error_code="validation_failed")
    assert get_skill_change(conn, cid)["error_code"] == "validation_failed"


def test_update_skill_change_rejects_bad_input(conn: sqlite3.Connection) -> None:
    cid = create_skill_change(conn, "regimen-folfox", "依頼", base_version=1)
    with pytest.raises(ValueError):
        update_skill_change(conn, cid, status="merged")
    with pytest.raises(ValueError):
        update_skill_change(conn, cid, skill_name="other")
    with pytest.raises(NotFoundError):
        update_skill_change(conn, 999, status="rejected")


def test_list_skill_changes(conn: sqlite3.Connection) -> None:
    a = create_skill_change(conn, "regimen-folfox", "1", base_version=1)
    b = create_skill_change(conn, "regimen-capox", "2", base_version=1)
    c = create_skill_change(conn, "regimen-folfox", "3", base_version=1)
    update_skill_change(conn, c, status="rejected")
    assert [x["id"] for x in list_skill_changes(conn)] == [a, b, c]
    assert [x["id"] for x in list_skill_changes(conn, skill_name="regimen-folfox")] == [
        a,
        c,
    ]
    assert [x["id"] for x in list_skill_changes(conn, statuses=("pending",))] == [a, b]


def test_list_skill_changes_empty_and_unknown_statuses(
    conn: sqlite3.Connection,
) -> None:
    create_skill_change(conn, "regimen-folfox", "1", base_version=1)
    assert list_skill_changes(conn, statuses=()) == []
    with pytest.raises(ValueError):
        list_skill_changes(conn, statuses=("pending", "merged"))


def test_update_skill_change_without_fields_is_noop(
    conn: sqlite3.Connection,
) -> None:
    cid = create_skill_change(conn, "regimen-folfox", "依頼", base_version=1)
    before = get_skill_change(conn, cid)
    update_skill_change(conn, cid)
    assert get_skill_change(conn, cid) == before
    with pytest.raises(NotFoundError):
        update_skill_change(conn, 999)


def test_get_skill_change_unknown_is_none(conn: sqlite3.Connection) -> None:
    assert get_skill_change(conn, 1) is None


def test_create_skill_change_rejects_bad_status(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        create_skill_change(
            conn, "regimen-folfox", "x", base_version=1, status="merged"
        )


# --- skill_versions ----------------------------------------------------------


def test_save_and_get_skill_version(conn: sqlite3.Connection) -> None:
    save_skill_version(conn, "regimen-folfox", 1, "---\nv1\n---\n", QUESTIONS)
    got = get_skill_version(conn, "regimen-folfox", 1)
    assert got is not None
    assert got["skill_name"] == "regimen-folfox"
    assert got["version"] == 1
    assert got["content"] == "---\nv1\n---\n"
    assert got["questions"] == QUESTIONS
    assert got["approved_at"].utcoffset() is not None
    raw = conn.execute(
        "SELECT questions_json FROM skill_versions WHERE skill_name=? AND version=?",
        ("regimen-folfox", 1),
    ).fetchone()[0]
    assert "手足のしびれ" in raw  # 日本語のまま保存


def test_skill_version_without_questions(conn: sqlite3.Connection) -> None:
    save_skill_version(conn, "report-format-default", 1, "body", None, approved_at=TS)
    got = get_skill_version(conn, "report-format-default", 1)
    assert got["questions"] is None
    assert got["approved_at"] == TS


def test_get_skill_version_unknown_is_none(conn: sqlite3.Connection) -> None:
    assert get_skill_version(conn, "regimen-folfox", 1) is None
    assert latest_skill_version(conn, "regimen-folfox") is None


def test_latest_skill_version(conn: sqlite3.Connection) -> None:
    save_skill_version(conn, "regimen-folfox", 1, "v1", QUESTIONS)
    save_skill_version(conn, "regimen-folfox", 3, "v3", QUESTIONS[:1])
    save_skill_version(conn, "regimen-folfox", 2, "v2", QUESTIONS)
    save_skill_version(conn, "regimen-capox", 9, "c9", QUESTIONS)
    latest = latest_skill_version(conn, "regimen-folfox")
    assert latest["version"] == 3
    assert latest["content"] == "v3"
    assert latest["questions"] == QUESTIONS[:1]


def test_save_skill_version_same_content_is_noop(conn: sqlite3.Connection) -> None:
    save_skill_version(conn, "regimen-folfox", 1, "v1", QUESTIONS, approved_at=TS)
    save_skill_version(conn, "regimen-folfox", 1, "v1", QUESTIONS)
    assert get_skill_version(conn, "regimen-folfox", 1)["approved_at"] == TS


def test_save_skill_version_is_immutable(conn: sqlite3.Connection) -> None:
    save_skill_version(conn, "regimen-folfox", 1, "v1", QUESTIONS)
    with pytest.raises(ValueError):
        save_skill_version(conn, "regimen-folfox", 1, "changed", QUESTIONS)
    assert get_skill_version(conn, "regimen-folfox", 1)["content"] == "v1"


def test_save_skill_version_rejects_bad_version(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        save_skill_version(conn, "regimen-folfox", 0, "v0", QUESTIONS)

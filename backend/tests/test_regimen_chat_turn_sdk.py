"""1往復の完了条件を、ScriptChat と SdkRegimenChat＋偽の query（ToolQuery）の両方で確かめる。

ScriptChat はツールの本体（handle_*）を直接呼ぶ。ToolQuery は build_options・SDK MCP
サーバー（jsonschema）・Hook（H1・H4）を通す。どちらでも同じ結果になること:

- ask が欄の id と選択肢を返す／先生の欄が守られる（頼まれたときだけ上書き）／
  薬の量を拒否する／ツールの値への H1 で拒否する
- Hook（H1・H4）のログが pipeline_logs（run_kind='regimen_chat'）に書かれ、文面が無い
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from regimen_chat_fakes import DENIED, ScriptChat, ToolQuery, change

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen.chat_sdk import SdkRegimenChat
from tsutae.regimen.chat_turn import run_turn
from tsutae.regimen.drafts import (
    create_new_draft,
    draft_form,
    open_skill_draft,
    patch_draft,
)
from tsutae.regimen.edit import FieldChange, FormPatch

KINDS = ["script", "sdk"]
TEXT = "1コースは14日。エルプラットの日も見直したい"


@dataclass
class Env:
    conn: sqlite3.Connection
    skills_dir: Path


@pytest.fixture
def env(tmp_path: Path, fixed_today: str) -> Iterator[Env]:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    conn = db.connect(tmp_path / "t.db")
    db.init_db(conn)
    skills_dir = home / ".claude" / "skills"
    ensure_skill_versions(conn, skills_dir)
    db.seed_question_library(conn)
    yield Env(conn, skills_dir)
    conn.close()


@dataclass
class Made:
    chat: Any
    query: ToolQuery | None


def _make(kind: str, calls: list[tuple[str, dict[str, Any]]]) -> Made:
    if kind == "script":
        return Made(ScriptChat(calls), None)
    query = ToolQuery(calls)
    return Made(SdkRegimenChat(get_settings(), query_fn=query), query)


def _run(env: Env, draft_id: int, chat: Any, text: str = TEXT) -> Any:
    return asyncio.run(
        run_turn(
            env.conn,
            draft_id,
            text,
            chat=chat,
            settings=get_settings(),
            skills_dir=env.skills_dir,
        )
    )


def _logs(env: Env, draft_id: int) -> list[dict[str, Any]]:
    rows = env.conn.execute(
        "SELECT * FROM pipeline_logs WHERE run_kind = 'regimen_chat' AND run_id = ?"
        " ORDER BY id",
        (draft_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _decisions(env: Env, draft_id: int, event: str) -> list[str | None]:
    return [r["decision"] for r in _logs(env, draft_id) if r["event"] == event]


def _is_error(made: Made, n: int) -> bool | None:
    """ToolQuery のときだけ、n 番目のツールの結果が is_error か。"""
    if made.query is None:
        return None
    return bool(made.query.outputs[n].is_error)


@pytest.mark.parametrize("kind", KINDS)
def test_ask_returns_field_id_and_options(env: Env, kind: str) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    ask = {
        "field": "drugs.4.days",
        "question": "ポンプは何日目に外しますか",
        "options": ["Day3", "Day2", "Day4"],
    }
    made = _make(kind, [("ask", ask)])
    outcome = _run(env, draft["id"], made.chat)
    assert outcome.error is None
    assert outcome.draft["chat"][-1]["ask"] == {
        "field_id": "drugs.d-fu-pump.days",
        "question": "ポンプは何日目に外しますか",
        "options": ["Day3", "Day2", "Day4"],
    }
    assert _is_error(made, 0) is (None if made.query is None else False)
    assert _decisions(env, draft["id"], "regimen_tool") == ["accept"]


@pytest.mark.parametrize("kind", KINDS)
def test_doctor_edit_is_protected_unless_requested(env: Env, kind: str) -> None:
    draft = create_new_draft(env.conn)
    patch_draft(
        env.conn,
        draft["id"],
        FormPatch(changes=(FieldChange("basic.cycle_days", 21),)),
        skills_dir=env.skills_dir,
        timeout_s=90,
    )
    made = _make(kind, [change("basic.cycle_days", 14)])
    outcome = _run(env, draft["id"], made.chat)
    assert draft_form(outcome.draft).basic.cycle_days == 21
    assert '"basic.cycle_days":"doctor_edit"' in outcome.draft["sources_json"]
    assert _is_error(made, 0) is (None if made.query is None else True)
    assert _decisions(env, draft["id"], "regimen_tool") == ["reject:doctor_edit"]

    name, args = change("basic.cycle_days", 14)
    made = _make(kind, [(name, {**args, "overwrite_requested": True})])
    outcome = _run(env, draft["id"], made.chat, "14日に変えて")
    assert draft_form(outcome.draft).basic.cycle_days == 14
    assert '"basic.cycle_days":"doctor_text"' in outcome.draft["sources_json"]


@pytest.mark.parametrize("kind", KINDS)
def test_dose_is_rejected(env: Env, kind: str) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    before = draft["form_json"]
    made = _make(kind, [change("drugs.1.name", "エルプラット 85mg/m2")])
    outcome = _run(env, draft["id"], made.chat)
    assert outcome.draft["form_json"] == before
    assert _is_error(made, 0) is (None if made.query is None else True)
    assert _decisions(env, draft["id"], "regimen_tool") == ["reject:dose"]
    assert _decisions(env, draft["id"], "turn_counts") == [
        "calls:1:rejected:1:turns:3:changed:0"
    ]
    assert "85mg" not in repr(_logs(env, draft["id"]))


@pytest.mark.parametrize("kind", KINDS)
def test_h1_on_tool_value_is_rejected(env: Env, kind: str) -> None:
    draft = create_new_draft(env.conn)
    made = _make(kind, [change("notes", "P-DEMO0001 の方は別")])
    outcome = _run(env, draft["id"], made.chat)
    assert draft_form(outcome.draft).notes == ""
    assert "P-DEMO0001" not in repr(outcome.draft)
    assert _is_error(made, 0) is (None if made.query is None else True)
    if made.query is not None:  # 拒否の理由に文面を返さない
        assert "P-DEMO0001" not in repr(made.query.outputs[0])
    assert _decisions(env, draft["id"], "regimen_tool") == ["reject:identifier"]
    assert "P-DEMO0001" not in repr(_logs(env, draft["id"]))


def test_hook_logs_are_written_to_pipeline_logs(env: Env) -> None:
    """H1（依頼文）・H4（3つ以外の拒否）の Hook のログが regimen_chat に書かれる。"""
    draft = create_new_draft(env.conn)
    made = _make(
        "sdk",
        [
            ("Bash", {"command": "cat ~/.claude/CLAUDE.md"}),
            ("Read", {"file_path": "/etc/hosts"}),
            change("basic.cycle_days", 14),
        ],
    )
    outcome = _run(env, draft["id"], made.chat)
    assert outcome.error is None
    assert draft_form(outcome.draft).basic.cycle_days == 14
    assert made.query is not None and made.query.outputs[:2] == [DENIED, DENIED]
    logs = _logs(env, draft["id"])
    events = [r["event"] for r in logs]
    assert events.count("hook_h1_allow") == 1
    assert events.count("hook_h4_deny") == 2
    assert events.count("hook_h4_allow") == 1
    denied_tools = [r["tool_name"] for r in logs if r["event"] == "hook_h4_deny"]
    assert denied_tools == ["Bash", "Read"]
    text = repr(logs)
    for secret in (TEXT, "CLAUDE.md", "/etc/hosts", "エルプラット"):
        assert secret not in text

"""ask の選択肢と直近の会話の H1（T94 の確かめ直し）。

ask の選択肢は次の往復の依頼文（直近の会話）に1行でつないで入る。つないだ形が H1 に
掛かると、その下書きのチャットは以後ずっと h1_blocked になる（往復が失敗すると会話が
進まない）。そこで:

- 選択肢は H1 の区切り（空白・「/」等）でない「」で囲んでつなぐ（数字の選択肢が
  1つの数字の並びにならない）
- ask は、依頼文に入るのと同じ形（`ask_line`）にも H1 を掛け、掛かれば拒否する
- 会話の行を描いて H1 に掛かる行は、固定の文に置き換える（既に詰まった下書きも戻れる）
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from regimen_chat_fakes import ScriptChat

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.db.repo_question_library import SEED_QUESTIONS
from tsutae.masking import detect_identifiers
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen import chat_tools
from tsutae.regimen.chat_prompt import (
    HISTORY_HIDDEN,
    ask_line,
    build_turn_prompt,
)
from tsutae.regimen.chat_session import ChatSession
from tsutae.regimen.chat_tools import handle_ask
from tsutae.regimen.chat_turn import run_turn
from tsutae.regimen.chat_types import LibraryItem, TurnInput
from tsutae.regimen.drafts import create_new_draft
from tsutae.regimen.form import FieldSources
from tsutae.regimen.source import new_draft_form

LIBRARY = tuple(LibraryItem(**dict(item)) for item in SEED_QUESTIONS)
DIGIT_OPTIONS = ["7", "14", "21", "28"]
DAY_OPTIONS = ["1・8・15", "1・15"]


def _input(history: tuple[dict[str, Any], ...] = ()) -> TurnInput:
    return TurnInput(
        draft_id=1,
        form=new_draft_form(),
        sources=FieldSources({}),
        library=LIBRARY,
        history=history,
    )


def _assistant(text: str, options: list[str] | None = None) -> dict[str, Any]:
    ask = (
        None
        if options is None
        else {
            "field_id": "basic.cycle_days",
            "question": "1コースは何日ですか",
            "options": options,
        }
    )
    return {
        "role": "assistant",
        "text": text,
        "changed": [],
        "ask": ask,
        "proposed": [],
        "reply_hidden": False,
        "generation": 1,
        "at": "2026-11-05 10:00:00",
    }


# ---------------------------------------------------------------------------
# 依頼文
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("options", [DIGIT_OPTIONS, DAY_OPTIONS])
def test_ask_line_with_digit_options_passes_h1(options: list[str]) -> None:
    line = ask_line("1コースは何日ですか", options)
    assert detect_identifiers(line) == []
    for option in options:
        assert f"「{option}」" in line


@pytest.mark.parametrize("options", [DIGIT_OPTIONS, DAY_OPTIONS])
def test_prompt_with_digit_ask_in_history_passes_h1(options: list[str]) -> None:
    history = (_assistant("1コースの日数を聞いています", options),)
    prompt = build_turn_prompt(_input(history), "21日で")
    assert detect_identifiers(prompt) == []
    assert "1コースは何日ですか" in prompt


def test_history_line_with_identifier_is_replaced() -> None:
    """描いた行が H1 に掛かる行（前の版で保存した行など）は固定の文にする。"""
    history = (
        {"role": "doctor", "text": "前の文", "generation": 1, "at": "x"},
        _assistant("Day 1, 8, 15, 22, 28 にしました"),
    )
    prompt = build_turn_prompt(_input(history), "次へ")
    assert detect_identifiers(prompt) == []
    assert "前の文" in prompt
    assert HISTORY_HIDDEN in prompt
    assert "22, 28" not in prompt
    assert detect_identifiers(HISTORY_HIDDEN) == []


# ---------------------------------------------------------------------------
# ask の検査
# ---------------------------------------------------------------------------


def _session() -> ChatSession:
    return ChatSession(_input())


def test_ask_with_digit_options_is_accepted() -> None:
    session = _session()
    result = handle_ask(
        {
            "field": "basic.cycle_days",
            "question": "1コースは何日ですか",
            "options": DIGIT_OPTIONS,
        },
        session,
    )
    assert not result.get("is_error"), result
    assert session.ask is not None and session.ask.options == tuple(DIGIT_OPTIONS)


def test_ask_is_rejected_when_the_rendered_line_hits_h1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """選択肢を1つずつ見て通っても、依頼文に入る形で掛かれば拒否する。"""
    monkeypatch.setattr(chat_tools, "ask_line", lambda q, o: "1234 5678")
    session = _session()
    result = handle_ask(
        {
            "field": "basic.cycle_days",
            "question": "1コースは何日ですか",
            "options": ["14日", "21日"],
        },
        session,
    )
    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "options" in text and "identifier" in text
    assert session.ask is None and session.rejected == 1


# ---------------------------------------------------------------------------
# 通し（run_turn）
# ---------------------------------------------------------------------------


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


def _run(env: Env, draft_id: int, text: str, chat: Any) -> Any:
    return asyncio.run(
        run_turn(
            env.conn,
            draft_id,
            text,
            chat=chat,
            settings=dataclasses.replace(get_settings()),
            skills_dir=env.skills_dir,
        )
    )


@pytest.mark.parametrize("options", [DIGIT_OPTIONS, DAY_OPTIONS])
def test_turn_after_a_digit_ask_is_not_blocked(env: Env, options: list[str]) -> None:
    draft = create_new_draft(env.conn)
    ask = {
        "field": "basic.cycle_days",
        "question": "1コースは何日ですか",
        "options": options,
    }
    first = _run(
        env, draft["id"], "1コースの日数を決めたい", ScriptChat([("ask", ask)])
    )
    assert first.error is None
    assert first.draft["chat"][-1]["ask"]["options"] == options
    for text in ("21日で", "28", "別の質問"):
        outcome = _run(env, draft["id"], text, ScriptChat())
        assert outcome.error is None


def test_stuck_draft_can_continue(env: Env) -> None:
    """前の版で保存した、描くと H1 に掛かる行があっても次の往復を送れる。"""
    draft = create_new_draft(env.conn)
    chat = [_assistant("Day 1, 8, 15, 22, 28 にしました")]
    env.conn.execute(
        "UPDATE regimen_drafts SET chat_json = ? WHERE id = ?",
        (json.dumps(chat, ensure_ascii=False), draft["id"]),
    )
    env.conn.commit()
    script = ScriptChat()
    outcome = _run(env, draft["id"], "次へ", script)
    assert outcome.error is None
    assert len(script.seen) == 1

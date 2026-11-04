"""tsutae.regimen.chat_turn: 1往復の実行と反映（POST .../turns の本体。偽の chat）。

- 入力の文と依頼文の全体に H1。掛かれば Claude を呼ばず h1_blocked（何も保存しない）
- working にして generation を上げてから chat.turn。working の間は 409 working
- 結果は working かつ同じ generation のときだけ反映（古い世代は捨てる）
- 時間切れ・例外なら open に戻し、会話に先生の文と失敗の行を残す
- ログ（regimen_chat）には種類・回数・費用・秒だけ（文面は入れない）
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ResultError
from regimen_chat_fakes import FailingChat, ScriptChat, SlowChat, change
from regimen_fixtures import extra_form, fill_patch

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.db import repo_regimen_drafts as repo
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen.chat_rows import REPLY_HIDDEN
from tsutae.regimen.chat_turn import run_turn
from tsutae.regimen.drafts import (
    DraftError,
    create_new_draft,
    draft_form,
    open_skill_draft,
    patch_draft,
)
from tsutae.regimen.edit import FieldChange, FormPatch

DOCTOR_TEXT = "1コースは14日。エルプラットは使わない"
REPLY = ScriptChat().reply


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


def _settings(**kw: Any) -> Any:
    return dataclasses.replace(get_settings(), **kw)


def _set(field_ref: str, value: Any, source: str = "doctor_text") -> tuple[str, dict]:
    return change(field_ref, value, source)


def _run(env: Env, draft_id: int, text: str, chat: Any, **kw: Any) -> Any:
    return asyncio.run(
        run_turn(
            env.conn,
            draft_id,
            text,
            chat=chat,
            settings=_settings(**kw),
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


# ---------------------------------------------------------------------------
# 反映
# ---------------------------------------------------------------------------


def test_turn_fills_fields_and_saves_chat(env: Env) -> None:
    draft = create_new_draft(env.conn)
    chat = ScriptChat(
        [
            _set("basic.cycle_days", 14),
            _set("basic.target", "大腸がん", "standard"),
            _set("basic.code", "FOLFIRI-BV"),
        ]
    )
    outcome = _run(env, draft["id"], DOCTOR_TEXT, chat)
    assert outcome.error is None
    got = outcome.draft
    assert got["status"] == "open" and got["generation"] == 1
    form = draft_form(got)
    assert form.basic.cycle_days == 14
    assert got["regimen"] == "FOLFIRI-BV"
    assert '"basic.target":"standard"' in got["sources_json"]
    doctor, assistant = got["chat"]
    assert doctor == {
        "role": "doctor",
        "text": DOCTOR_TEXT,
        "generation": 1,
        "at": doctor["at"],
    }
    assert assistant["role"] == "assistant"
    assert assistant["text"] == REPLY
    assert assistant["changed"] == ["basic.cycle_days", "basic.target", "basic.code"]
    assert assistant["ask"] is None and assistant["proposed"] == []
    assert assistant["generation"] == 1
    # chat に渡した下書きは往復の始まりの値
    seen, text = chat.seen[0]
    assert text == DOCTOR_TEXT and seen.allow_code and seen.history == ()


def test_ask_is_saved_with_field_id_and_options(env: Env) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    ask = {
        "field": "drugs.4.days",
        "question": "ポンプは何日目に外しますか",
        "options": ["Day3", "Day2", "Day4"],
    }
    outcome = _run(
        env, draft["id"], "ポンプの日を見直したい", ScriptChat([("ask", ask)])
    )
    assistant = outcome.draft["chat"][-1]
    assert assistant["ask"] == {
        "field_id": "drugs.d-fu-pump.days",
        "question": "ポンプは何日目に外しますか",
        "options": ["Day3", "Day2", "Day4"],
    }
    assert assistant["changed"] == []
    # 次の往復の依頼文には前の会話が入る
    chat = ScriptChat()
    _run(env, draft["id"], "Day3 で", chat)
    assert [r["role"] for r in chat.seen[0][0].history] == ["doctor", "assistant"]


def test_doctor_edit_is_protected(env: Env) -> None:
    draft = create_new_draft(env.conn)
    draft = patch_draft(
        env.conn,
        draft["id"],
        FormPatch(changes=(FieldChange("basic.cycle_days", 21),)),
        skills_dir=env.skills_dir,
        timeout_s=90,
    )
    chat = ScriptChat([_set("basic.cycle_days", 14)])
    outcome = _run(env, draft["id"], "14日にして", chat)
    assert draft_form(outcome.draft).basic.cycle_days == 21
    assert outcome.draft["chat"][-1]["changed"] == []
    assert '"basic.cycle_days":"doctor_edit"' in outcome.draft["sources_json"]


def test_dose_is_rejected(env: Env) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    before = draft["form_json"]
    chat = ScriptChat([_set("drugs.1.name", "オキサリプラチン 85mg/m2")])
    outcome = _run(env, draft["id"], "量も書いて", chat)
    assert outcome.draft["form_json"] == before
    counts = [r for r in _logs(env, draft["id"]) if r["event"] == "turn_counts"]
    assert counts[0]["decision"] == "calls:1:rejected:1:turns:3:changed:0"


# ---------------------------------------------------------------------------
# H1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["受付 A-023 の件", "磯鷲さんの件"])
def test_h1_on_input_does_not_call_claude_or_save(env: Env, text: str) -> None:
    draft = create_new_draft(env.conn)
    chat = ScriptChat()
    with pytest.raises(DraftError) as info:
        _run(env, draft["id"], text, chat)
    assert info.value.code == "h1_blocked"
    assert chat.seen == []
    got = repo.get_draft(env.conn, draft["id"])
    assert got["generation"] == 0 and got["chat"] == [] and got["status"] == "open"
    [check] = [r for r in _logs(env, draft["id"]) if r["event"] == "h1_check"]
    assert check["decision"].startswith("block:")


def test_h1_on_whole_prompt(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """入力の文に掛からなくても、組み立てた依頼文の全体に掛かれば止める。"""
    from tsutae.regimen import chat_turn

    monkeypatch.setattr(
        chat_turn, "build_turn_prompt", lambda draft, text: f"{text}\nP-DEMO0001"
    )
    draft = create_new_draft(env.conn)
    chat = ScriptChat()
    with pytest.raises(DraftError) as info:
        _run(env, draft["id"], DOCTOR_TEXT, chat)
    assert info.value.code == "h1_blocked"
    assert chat.seen == []
    assert repo.get_draft(env.conn, draft["id"])["generation"] == 0


def test_h1_on_tool_value_rejects_the_change(env: Env) -> None:
    draft = create_new_draft(env.conn)
    chat = ScriptChat([_set("notes", "P-DEMO0001 の方は別")])
    outcome = _run(env, draft["id"], DOCTOR_TEXT, chat)
    assert draft_form(outcome.draft).notes == ""
    assert "P-DEMO0001" not in repr(outcome.draft)


def test_reply_with_identifier_is_hidden(env: Env) -> None:
    draft = create_new_draft(env.conn)
    chat = ScriptChat([_set("basic.cycle_days", 14)], reply="磯鷲さんの件で直した")
    outcome = _run(env, draft["id"], DOCTOR_TEXT, chat)
    assistant = outcome.draft["chat"][-1]
    assert assistant["text"] == REPLY_HIDDEN
    assert assistant["reply_hidden"] is True
    assert draft_form(outcome.draft).basic.cycle_days == 14


# ---------------------------------------------------------------------------
# 失敗・世代
# ---------------------------------------------------------------------------


def test_timeout_returns_to_open_with_failed_row(env: Env) -> None:
    draft = create_new_draft(env.conn)
    outcome = _run(
        env, draft["id"], DOCTOR_TEXT, SlowChat(), regimen_turn_timeout_s=0.05
    )
    assert outcome.error == "timeout"
    got = outcome.draft
    assert got["status"] == "open" and got["working_since"] is None
    doctor, failed = got["chat"]
    assert doctor["role"] == "doctor" and doctor["text"] == DOCTOR_TEXT
    assert {k: failed[k] for k in ("role", "kind", "reason", "generation")} == {
        "role": "system",
        "kind": "turn_failed",
        "reason": "timeout",
        "generation": 1,
    }
    assert draft_form(got) == draft_form(draft)
    [end] = [r for r in _logs(env, draft["id"]) if r["event"] == "turn_end"]
    assert end["decision"] == "timeout"


@pytest.mark.parametrize(
    "exc, code",
    [
        (ResultError("秘密の文", {"subtype": "error_max_budget_usd"}), "max_budget"),
        (RuntimeError("秘密の文"), "internal_error"),
    ],
)
def test_errors_return_to_open(env: Env, exc: Exception, code: str) -> None:
    draft = create_new_draft(env.conn)
    outcome = _run(env, draft["id"], DOCTOR_TEXT, FailingChat(exc))
    assert outcome.error == code
    assert outcome.draft["status"] == "open"
    assert outcome.draft["chat"][-1]["reason"] == code
    assert "秘密" not in repr(_logs(env, draft["id"]))


def test_working_draft_is_busy(env: Env) -> None:
    draft = create_new_draft(env.conn)
    repo.begin_working(env.conn, draft["id"])
    chat = ScriptChat()
    with pytest.raises(DraftError) as info:
        _run(env, draft["id"], DOCTOR_TEXT, chat)
    assert info.value.code == "working"
    assert chat.seen == []


def test_closed_draft_is_not_open(env: Env) -> None:
    draft = create_new_draft(env.conn)
    repo.discard_draft(env.conn, draft["id"])
    with pytest.raises(DraftError) as info:
        _run(env, draft["id"], DOCTOR_TEXT, ScriptChat())
    assert info.value.code == "not_open"
    with pytest.raises(DraftError) as missing:
        _run(env, 999, DOCTOR_TEXT, ScriptChat())
    assert missing.value.code == "not_found"


def test_result_of_an_old_generation_is_discarded(env: Env) -> None:
    """往復の間に回復（open に戻す）と次の往復が入れば、遅れた結果は捨てる。"""
    draft = create_new_draft(env.conn)

    async def interrupt() -> None:
        repo.recover_stale_working(env.conn, timeout_s=0)
        repo.begin_working(env.conn, draft["id"])  # 次の往復（generation 2）

    chat = ScriptChat([_set("basic.cycle_days", 14)], before_return=interrupt)
    outcome = _run(env, draft["id"], DOCTOR_TEXT, chat)
    assert outcome.error == "discarded"
    got = repo.get_draft(env.conn, draft["id"])
    assert got["generation"] == 2 and got["status"] == "working"
    assert draft_form(got).basic.cycle_days is None
    assert [r.get("role") for r in got["chat"]] == ["system"]  # 回復の行だけ


def test_logs_have_counts_and_no_text(env: Env) -> None:
    draft = create_new_draft(env.conn)
    patch = fill_patch(draft_form(draft), extra_form("folfiri_bv"))
    draft = patch_draft(
        env.conn, draft["id"], patch, skills_dir=env.skills_dir, timeout_s=90
    )
    ask = {
        "field": "notes",
        "question": "施設の決まりはありますか",
        "options": ["ある", "ない"],
    }
    chat = ScriptChat(
        [
            _set("drugs.1.name", "ベバシズマブ 5mg/kg"),
            _set("notes", "連絡は外来へ"),
            ("ask", ask),
        ],
        reply="補足の指示を入れました",
    )
    _run(env, draft["id"], DOCTOR_TEXT, chat)
    logs = _logs(env, draft["id"])
    events = [r["event"] for r in logs]
    assert events[:2] == ["h1_check", "turn_start"]
    assert {"turn_end", "turn_counts"} <= set(events)
    [end] = [r for r in logs if r["event"] == "turn_end"]
    assert end["decision"] == "ok"
    assert (end["duration_ms"], end["tokens_in"], end["tokens_out"]) == (800, 40, 8)
    assert end["cost_usd"] == pytest.approx(0.04)
    [counts] = [r for r in logs if r["event"] == "turn_counts"]
    assert counts["decision"] == "calls:3:rejected:1:turns:3:changed:1"
    text = repr(logs)
    for secret in (
        DOCTOR_TEXT,
        "エルプラット",
        "補足の指示を入れました",
        "連絡は外来へ",
        "施設の決まりはありますか",
        "ベバシズマブ",
    ):
        assert secret not in text


class RawChat:
    """ツールを通らない結果を返す chat（RegimenChat を差し替えたときの守り）。"""

    def __init__(self, update: dict[str, Any], ask: Any = None) -> None:
        self.update = update
        self.ask = ask

    async def turn(self, draft: Any, text: str) -> Any:
        from tsutae.regimen.chat_types import TurnResult

        basic = draft.form.basic.model_copy(update=self.update)
        form = draft.form.model_copy(update={"basic": basic})
        return TurnResult(form=form, sources=draft.sources, reply="x", ask=self.ask)


def test_result_that_skipped_the_checks_is_not_written(env: Env) -> None:
    draft = create_new_draft(env.conn)
    outcome = _run(env, draft["id"], DOCTOR_TEXT, RawChat({"cycle_days": 99}))
    assert outcome.error == "invalid_result"
    assert draft_form(outcome.draft).basic.cycle_days is None
    assert outcome.draft["chat"][-1]["reason"] == "invalid_result"


def test_ask_with_identifier_is_dropped(env: Env) -> None:
    from tsutae.regimen.chat_types import AskOut

    draft = create_new_draft(env.conn)
    ask = AskOut("notes", "受付 A-023 の方と同じですか", ("はい", "いいえ"))
    outcome = _run(env, draft["id"], DOCTOR_TEXT, RawChat({"cycle_days": 14}, ask))
    assert outcome.error is None
    assert outcome.draft["chat"][-1]["ask"] is None
    assert "A-023" not in repr(outcome.draft["chat"])

"""tsutae.skillchange.check（書き換えの後の検査。PostToolUse の Hook）。API は呼ばない。

- 壊れた frontmatter・変えられた version には、どこがどう違うかを返して直させる
- 正しい内容には {} を返す。ログには規則のコードだけ（文面なし）
- デモの依頼「口内炎は、食事がとれたかも次から聞いて」の流れ（偽の editor）
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ResultMessage

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.service import questions_by_version
from tsutae.schemas import RunStats
from tsutae.skillchange import SdkSkillEditor, approve_change, request_change
from tsutae.skillchange.check import (
    SKILL_CHECK_MATCHER,
    Baseline,
    baseline_of,
    check_skill_text,
    make_skill_check,
    read_baseline,
)
from tsutae.skillchange.editor import build_options

NAME = "regimen-folfox"
REPORT = "report-format-default"
DEMO_REQUEST = "口内炎は、食事がとれたかも次から聞いて"
STOMATITIS_LINE = (
    "  - {key: stomatitis, text: 口の中の痛みや口内炎はありましたか,"
    " answer_type: three_level}\n"
)
EATING_LINE = (
    "  - {key: stomatitis_eating, text: 口の中が痛くて食事がとりにくいことは"
    "ありましたか, answer_type: three_level}\n"
)


def _original(name: str = NAME) -> str:
    return (SKILLS_HOME / ".claude" / "skills" / name / "SKILL.md").read_text("utf-8")


def _add_eating_question(text: str) -> str:
    assert STOMATITIS_LINE in text
    return text.replace(STOMATITIS_LINE, STOMATITIS_LINE + EATING_LINE)


@pytest.fixture
def work_root(tmp_path: Path) -> Path:
    root = (tmp_path / "work").resolve()
    for name in (NAME, REPORT):
        path = root / ".claude" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(_original(name), "utf-8")
    return root


def _copy(work_root: Path, name: str = NAME) -> Path:
    return work_root / ".claude" / "skills" / name / "SKILL.md"


def _post(tool: str, path: Path | str | None) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {"file_path": None if path is None else str(path)},
        "tool_response": {},
        "tool_use_id": "t1",
    }


def _context(result: dict) -> str:
    out = result["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    assert result["decision"] == "block"
    assert result["reason"] == out["additionalContext"]
    assert "continue" not in result and "continue_" not in result
    return out["additionalContext"]


# ---------------------------------------------------------------------------
# check_skill_text（純関数）
# ---------------------------------------------------------------------------


def test_valid_text_has_no_problem() -> None:
    assert check_skill_text(NAME, _original(), 1) is None
    assert check_skill_text(NAME, _add_eating_question(_original()), 1) is None
    assert check_skill_text(REPORT, _original(REPORT), 1) is None


@pytest.mark.parametrize(
    ("transform", "code", "where"),
    [
        (
            lambda t: t.replace("key: stomatitis,", "key: Stomatitis-2,"),
            "schema",
            "questions.2.key",
        ),
        (
            lambda t: t.replace(
                "下痢はありましたか, answer_type: three_level",
                "下痢はありましたか, answer_type: yes_no",
            ),
            "schema",
            "questions.1.answer_type",
        ),
        (
            lambda t: t.replace("question_key: fever,", "question_key: fever_temp,"),
            "schema",
            "fixed_rule",
        ),
        (lambda t: t.replace("version: 1\n", "version: 2\n"), "version_changed", "1"),
        (
            lambda t: t.replace("version: 1\n", "version: 1\nversion: 1\n"),
            "format",
            "重複",
        ),
        (lambda t: t.replace("name: regimen-folfox", "name: regimen-x"), "name", NAME),
        (
            lambda t: t.replace("pump_removal_day: 3", "pump_removal_day: 20"),
            "schema",
            "pump_removal_day",
        ),
        (
            lambda t: t.replace("threshold_celsius: 38.0", "threshold_celsius: 50"),
            "schema",
            "threshold_celsius",
        ),
        (lambda t: t.replace("\n---\n", "\n", 1), "format", ""),
    ],
)
def test_broken_text_has_code_and_reason(transform, code: str, where: str) -> None:
    problem = check_skill_text(NAME, transform(_original()), 1)
    assert problem is not None
    got_code, reason = problem
    assert got_code.startswith(code)
    assert where in reason
    assert re.fullmatch(r"[a-z_]+", got_code)


def test_reason_names_the_rules() -> None:
    text = _original().replace("key: stomatitis,", "key: Stomatitis-2,")
    _code, reason = check_skill_text(NAME, text, 1)  # type: ignore[misc]
    assert "questions.2.key" in reason
    assert "three_level" in reason and "temperature" in reason
    text = _original().replace("version: 1\n", "version: 2\n")
    _code, reason = check_skill_text(NAME, text, 1)  # type: ignore[misc]
    assert "version" in reason and "変えない" in reason


def test_version_line_that_cannot_be_bumped_is_a_problem() -> None:
    # 検査は通るが、承認の時に set_version で版を上げられない書き方
    text = _original().replace("version: 1\n", '"version": 1\n')
    problem = check_skill_text(NAME, text, 1)
    assert problem is not None and problem[0] == "version_line"


def test_without_base_version_only_validates() -> None:
    text = _original().replace("version: 1\n", "version: 3\n")
    assert check_skill_text(NAME, text, None) is None


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


def test_baseline_of_regimen_and_report() -> None:
    assert baseline_of(NAME, _original()) == Baseline(
        version=1,
        question_keys=(
            "numbness",
            "diarrhea",
            "stomatitis",
            "nausea_appetite",
            "fever",
        ),
    )
    assert baseline_of(REPORT, _original(REPORT)) == Baseline(1, ())
    assert baseline_of(NAME, "壊れた") == Baseline(None, ())


def test_read_baseline(work_root: Path) -> None:
    assert read_baseline(work_root, NAME).version == 1
    assert read_baseline(work_root, "regimen-capox") == Baseline(None, ())


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------


async def test_hook_returns_empty_for_valid_edit(work_root: Path) -> None:
    logger = MemoryLogger()
    hook = make_skill_check(work_root, NAME, 1, logger)
    copy = _copy(work_root)
    copy.write_text(_add_eating_question(copy.read_text("utf-8")), "utf-8")
    for tool in ("Edit", "Write"):
        assert await hook(_post(tool, copy), "t1", None) == {}
    assert logger.names() == ["hook_skill_check_allow"] * 2
    assert logger.records[0]["decision"] == "allow"


async def test_hook_returns_reason_for_broken_frontmatter(work_root: Path) -> None:
    logger = MemoryLogger()
    hook = make_skill_check(work_root, NAME, 1, logger)
    copy = _copy(work_root)
    secret = "口の中が痛くて秘密の文"
    broken = copy.read_text("utf-8").replace(
        STOMATITIS_LINE,
        STOMATITIS_LINE + f"  - {{key: Eating, text: {secret}, answer_type: yes_no}}\n",
    )
    copy.write_text(broken, "utf-8")
    reason = _context(await hook(_post("Edit", copy), "t1", None))
    assert "questions.3.key" in reason and "questions.3.answer_type" in reason
    assert ".claude/skills/regimen-folfox/SKILL.md" in reason
    [record] = logger.find("hook_skill_check_retry")
    assert record["decision"] == "retry:schema"
    assert record["hook_name"] == "skill_check"
    assert secret not in repr(logger.records)
    assert "Eating" not in repr(logger.records)


async def test_hook_returns_reason_for_changed_version(work_root: Path) -> None:
    logger = MemoryLogger()
    hook = make_skill_check(work_root, NAME, 1, logger)
    copy = _copy(work_root)
    copy.write_text(
        _add_eating_question(copy.read_text("utf-8")).replace(
            "version: 1\n", "version: 2\n"
        ),
        "utf-8",
    )
    reason = _context(await hook(_post("Write", copy), "t1", None))
    assert "version" in reason and "1" in reason
    assert logger.find("hook_skill_check_retry")[0]["decision"] == (
        "retry:version_changed"
    )


async def test_hook_tells_model_only_target_file_counts(work_root: Path) -> None:
    logger = MemoryLogger()
    hook = make_skill_check(work_root, NAME, 1, logger)
    reason = _context(await hook(_post("Write", _copy(work_root, REPORT)), "t", None))
    assert f".claude/skills/{NAME}/SKILL.md" in reason
    assert logger.find("hook_skill_check_retry")[0]["decision"] == ("retry:other_file")


async def test_hook_missing_or_unreadable_file_does_not_raise(
    work_root: Path,
) -> None:
    logger = MemoryLogger()
    hook = make_skill_check(work_root, NAME, 1, logger)
    copy = _copy(work_root)
    copy.write_bytes(b"\xff\xfe\x00broken")
    assert "UTF-8" in _context(await hook(_post("Edit", copy), "t", None))
    copy.unlink()
    assert _context(await hook(_post("Edit", copy), "t", None))
    assert _context(await hook(_post("Edit", None), "t", None))
    assert await hook("not a dict", "t", None) == {}  # type: ignore[arg-type]


async def test_hook_ignores_other_tools(work_root: Path) -> None:
    logger = MemoryLogger()
    hook = make_skill_check(work_root, NAME, 1, logger)
    assert await hook(_post("Read", _copy(work_root)), "t", None) == {}
    assert logger.records == []


def test_options_have_post_tool_use_check(work_root: Path) -> None:
    options = build_options(
        work_root, get_settings(), MemoryLogger(), skill_name=NAME, base_version=1
    )
    [matcher] = options.hooks["PostToolUse"]  # type: ignore[index]
    assert matcher.matcher == SKILL_CHECK_MATCHER == "Write|Edit|MultiEdit"
    assert matcher.on_failure == "block"
    assert len(matcher.hooks) == 1


# ---------------------------------------------------------------------------
# デモの依頼の流れ（request → pending → approve → version 2）
# ---------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


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


class DemoEditor:
    """デモの依頼どおり、stomatitis の後に three_level の質問を1つ足す。"""

    def __init__(self) -> None:
        self.requests: list[str] = []

    async def edit(
        self, work_root: Path, skill_name: str, request_text: str
    ) -> RunStats:
        self.requests.append(request_text)
        path = work_root / ".claude" / "skills" / skill_name / "SKILL.md"
        path.write_text(_add_eating_question(path.read_text("utf-8")), "utf-8")
        return RunStats(duration_ms=10, num_turns=3)


async def test_demo_request_flow_reaches_version_2(conn, home, settings) -> None:
    editor = DemoEditor()
    cid = await request_change(
        conn, NAME, DEMO_REQUEST, editor=editor, settings=settings, skills_home=home
    )
    change = db.get_skill_change(conn, cid)
    assert (change["status"], change["error_code"]) == ("pending", None)
    assert editor.requests == [DEMO_REQUEST]
    assert "+" + EATING_LINE in change["diff"]
    assert approve_change(conn, cid, skills_home=home) == 2
    got = questions_by_version(conn, versions=[f"{NAME}@2"])
    keys = [q.key for q in got[f"{NAME}@2"]]
    assert keys == [
        "numbness",
        "diarrhea",
        "stomatitis",
        "stomatitis_eating",
        "nausea_appetite",
        "fever",
    ]
    eating = got[f"{NAME}@2"][3]
    assert eating.answer_type == "three_level"


async def test_sdk_editor_hook_lets_model_fix_then_pending(
    conn, home, settings
) -> None:
    """偽の query の中で、壊れた書き込み → Hook の理由 → 直す、をなぞる。"""
    seen: list[dict] = []

    async def fake_query(*, prompt: str, options):
        assert "stomatitis" in prompt and "nausea_appetite" in prompt
        [post] = options.hooks["PostToolUse"]
        path = Path(options.cwd) / ".claude" / "skills" / NAME / "SKILL.md"
        good = _add_eating_question(path.read_text("utf-8"))
        path.write_text(good.replace("key: stomatitis_eating", "key: Eating"), "utf-8")
        seen.append(await post.hooks[0](_post("Edit", path), "t1", None))
        path.write_text(good, "utf-8")
        seen.append(await post.hooks[0](_post("Edit", path), "t2", None))
        yield ResultMessage(
            subtype="success",
            duration_ms=700,
            duration_api_ms=600,
            is_error=False,
            num_turns=5,
            session_id="s",
            total_cost_usd=0.05,
            usage={"input_tokens": 11, "output_tokens": 4},
        )

    editor = SdkSkillEditor(settings, query_fn=fake_query)
    cid = await request_change(
        conn, NAME, DEMO_REQUEST, editor=editor, settings=settings, skills_home=home
    )
    assert "questions.3.key" in _context(seen[0])
    assert seen[1] == {}
    assert db.get_skill_change(conn, cid)["status"] == "pending"
    logs = db.list_pipeline_logs(conn, "skill_change", cid)
    events = [r["event"] for r in logs]
    assert events.index("hook_skill_check_retry") < events.index(
        "hook_skill_check_allow"
    )
    assert "Eating" not in repr(logs)

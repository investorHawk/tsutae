"""Agent SDK の1回の実行が `~/.claude/projects/` に残したファイルを消す（spec 13.3）。

`--no-session-persistence` で会話の記録（`<session>.jsonl`）は書かれないが、CLI は
サブエージェントの `<encoded-cwd>/<session>/subagents/agent-*.meta.json`（モデルが書いた
description を含む）を書く。実行の後に、そのセッションのファイルを消す。

- `session_id_of(message)`: メッセージの session_id（SystemMessage は data の session_id。
  init に入る）。UUID の形でなければ None（`..`・`/` などでパスの外へ出させない）
- `projects_dir()`: `$CLAUDE_CONFIG_DIR/projects`（未設定・空なら `~/.claude/projects`）
- `remove_session_files(ids, root=None)`: root の直下の各ディレクトリから `<id>/` と
  `<id>.jsonl` を消し、消した数を返す。シンボリックリンクはたどらない（直下の
  ディレクトリ・`<id>/`・`<id>.jsonl` のどれでも）。例外は出さない。ログはイベント名と
  例外の型名だけ（パス・文面は書かない）
- `query_cleaned(query_fn, prompt=, options=, projects_root=None)`: query の
  メッセージをそのまま流しながら session_id を集め、終わり（成功・例外・取り消し・
  途中で閉じた時）に、元の query を閉じて（CLI を止めて）から消す。root は消す時に決める
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, SystemMessage

__all__ = [
    "projects_dir",
    "query_cleaned",
    "remove_session_files",
    "session_id_of",
]

_SESSION_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_log = logging.getLogger(__name__)


def _valid(value: Any) -> str | None:
    if isinstance(value, str) and _SESSION_ID_RE.fullmatch(value):
        return value
    return None


def session_id_of(message: Any) -> str | None:
    """メッセージの session_id。UUID の形でなければ None。"""
    found = _valid(getattr(message, "session_id", None))
    if found is None and isinstance(message, SystemMessage):
        data = message.data
        if isinstance(data, Mapping):
            found = _valid(data.get("session_id"))
    return found


def projects_dir() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "projects"
    return Path.home() / ".claude" / "projects"


def _warn(event: str, exc: OSError) -> None:
    _log.warning("%s: %s", event, type(exc).__name__)


def _project_dirs(root: Path) -> list[Path]:
    try:
        return [p for p in root.iterdir() if not p.is_symlink() and p.is_dir()]
    except FileNotFoundError:
        return []
    except OSError as exc:
        _warn("session_files_list_failed", exc)
        return []


def _remove_dir(path: Path) -> int:
    try:
        if path.is_symlink() or not path.is_dir():
            return 0
        shutil.rmtree(path)
        return 1
    except OSError as exc:
        _warn("session_files_remove_failed", exc)
        return 0


def _remove_file(path: Path) -> int:
    try:
        if path.is_symlink() or not path.is_file():
            return 0
        path.unlink()
        return 1
    except OSError as exc:
        _warn("session_files_remove_failed", exc)
        return 0


def remove_session_files(session_ids: Iterable[str], root: Path | None = None) -> int:
    """各プロジェクトの `<id>/` と `<id>.jsonl` を消す。消した数を返す（例外は出さない）。"""
    ids = sorted({sid for sid in session_ids if _valid(sid) is not None})
    if not ids:
        return 0
    base = root if root is not None else projects_dir()
    removed = 0
    for project in _project_dirs(base):
        for sid in ids:
            removed += _remove_dir(project / sid)
            removed += _remove_file(project / f"{sid}.jsonl")
    return removed


async def _close(stream: Any) -> None:
    aclose = getattr(stream, "aclose", None)
    if aclose is None:
        return
    with suppress(Exception):
        await aclose()


async def query_cleaned(
    query_fn: Callable[..., AsyncIterator[Any]],
    *,
    prompt: str,
    options: ClaudeAgentOptions,
    projects_root: Path | None = None,
) -> AsyncIterator[Any]:
    """query のメッセージを流し、終わりに query を閉じてからセッションのファイルを消す。"""
    stream = query_fn(prompt=prompt, options=options)
    seen: set[str] = set()
    try:
        async for message in stream:
            sid = session_id_of(message)
            if sid is not None:
                seen.add(sid)
            yield message
    finally:
        await _close(stream)
        remove_session_files(seen, projects_root)

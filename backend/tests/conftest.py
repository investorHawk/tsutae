"""共通のテスト設定。

- API を呼ぶテストは `@pytest.mark.api` を付ける。ANTHROPIC_API_KEY が無ければ skip
- `.env` はサンドボックス内では読めない（読めなくても例外にしない）
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tsutae.config import load_env_file

load_env_file()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    skip = pytest.mark.skip(reason="ANTHROPIC_API_KEY が無い（API を呼ぶテスト）")
    for item in items:
        if "api" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """「今日」を固定する。値を変えたいときは monkeypatch.setenv で上書き。"""
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")
    # 固定日の時計の起点はテストごとに取り直す（スイートが実時間の0時をまたいでも、
    # 1つのテストの中でなければ日付が変わらない）
    from tsutae import config

    monkeypatch.setattr(config, "_FIXED_ANCHORS", {})
    yield "2026-11-09"

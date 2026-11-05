"""Funnel の手順の文書。開発サーバーをインターネットに出さない（decisions に理由）。

Vite 5.4.8 の開発サーバーは `/@fs/<絶対パス>?import&raw??` で `server.fs` の検査を抜け、
`.env` や DB まで読める。Funnel には `vite preview`（dist だけを返す）を出す。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREVIEW = "npx vite preview --host 127.0.0.1 --port 5173 --strictPort"
# npx vite / npx vite --host ...（build と preview は除く）・make dev-web
_DEV_SERVER = re.compile(r"npx vite(?! (?:build|preview)\b)|make dev-web")


def _section(path: str, start: str, end: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    return text[text.index(start) : text.index(end, text.index(start))]


def _code_lines(section: str) -> list[str]:
    """コードの囲みの中の行（実際に打つコマンド）。"""
    blocks = re.findall(r"```bash\n(.*?)```", section, flags=re.DOTALL)
    return [line for block in blocks for line in block.splitlines()]


FUNNEL_SECTIONS = {
    "README": lambda: _section("README.md", "毎日の通知を試す", "- ホーム画面に置く"),
    "plan": lambda: _section(
        "docs/plan-device-records.md", "### HTTPS: Tailscale Funnel", "### 実機"
    ),
}


@pytest.mark.parametrize("name", FUNNEL_SECTIONS)
def test_funnel_steps_start_preview_not_the_dev_server(name: str) -> None:
    lines = _code_lines(FUNNEL_SECTIONS[name]())
    assert any("tailscale funnel" in line for line in lines)
    assert any("npm run build" in line and PREVIEW in line for line in lines)
    assert [line for line in lines if _DEV_SERVER.search(line)] == []


@pytest.mark.parametrize("name", FUNNEL_SECTIONS)
def test_funnel_steps_warn_about_the_dev_server(name: str) -> None:
    section = FUNNEL_SECTIONS[name]()
    assert "開発サーバーは出さない" in section
    assert "?import&raw??" in section


def test_demo_script_does_not_send_funnel_to_the_dev_server() -> None:
    before = _section("docs/demo-script.md", "## 撮影の前に", "## 流れ")
    assert "開発サーバーは Funnel に出さない" in before
    assert "vite preview" in before


def test_architecture_says_preview() -> None:
    text = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    assert "Tailscale Funnel → `vite preview` の 5173" in text

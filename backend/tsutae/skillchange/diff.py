"""SKILL.md の差分（unified diff）と、frontmatter の version 行の書き換え。

- `unified(old, new)`: 同じなら空文字。行末の改行が無い行には difflib の流儀どおり
  `\\ No newline at end of file` を付ける（差分の各行は必ず改行で終わる）
- `set_version(text, version)`: frontmatter（最初の2つの `---` の間）にある字下げなしの
  `version:` 行だけを `version: N` に置き換える。行末（LF・CRLF）と BOM は保つ。
  その行がちょうど1つでなければ `SkillChangeError("version_line")`
"""

from __future__ import annotations

import difflib
import re

from tsutae.skillchange.errors import SkillChangeError

__all__ = ["set_version", "unified"]

_FENCE = "---"
_BOM = "﻿"
_VERSION_LINE = re.compile(r"version[ \t]*:")
_NO_NEWLINE = "\\ No newline at end of file\n"
# 行は "\n" だけで切る（str.splitlines は U+2028・\x0c なども行の区切りにする）
_LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")


def _lines(text: str) -> list[str]:
    return _LINE.findall(text)


def _with_newlines(lines: list[str]) -> list[str]:
    return [
        line if line.endswith("\n") else line + "\n" + _NO_NEWLINE for line in lines
    ]


def unified(old: str, new: str, *, path: str = "SKILL.md") -> str:
    """old → new の unified diff（文脈3行）。差が無ければ空文字。"""
    if old == new:
        return ""
    lines = difflib.unified_diff(
        _lines(old),
        _lines(new),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(_with_newlines(list(lines)))


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    return "\n" if line.endswith("\n") else ""


def _frontmatter_end(lines: list[str]) -> int:
    """閉じの `---` の位置。frontmatter が無い・閉じていなければ version_line。"""
    if not lines or lines[0].removeprefix(_BOM).rstrip() != _FENCE:
        raise SkillChangeError("version_line")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == _FENCE:
            return i
    raise SkillChangeError("version_line")


def set_version(text: str, version: int) -> str:
    """frontmatter の version を `version` に置き換えた新しい文を返す。"""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version は1以上の整数")
    lines = _lines(text)
    end = _frontmatter_end(lines)
    found = [i for i in range(1, end) if _VERSION_LINE.match(lines[i])]
    if len(found) != 1:
        raise SkillChangeError("version_line")
    i = found[0]
    replaced = f"version: {version}{_line_ending(lines[i])}"
    return "".join([*lines[:i], replaced, *lines[i + 1 :]])

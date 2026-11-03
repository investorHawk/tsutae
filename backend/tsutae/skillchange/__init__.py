"""Skill の書き換え（D4。docs/architecture.md §9b）。

- editor: SkillEditor プロトコルと SdkSkillEditor（Agent SDK。H1・H3・H4）
- service: request_change（写しを直させて差分を作る。一時ディレクトリの後始末）
- approve: approve_change・reject_change（Skill のディレクトリの flock の内側で。
  途中で落ちた承認はもう一度の承認で再開する）
- lock: Skill ごとのプロセス間ロック（busy）。state: pending の行だけの条件付き更新
- diff: unified diff と frontmatter の version 行の書き換え
- errors: SkillChangeError（`code` を API が `{"error": code}` にする）と
  `status_for(code)`（HTTP の status）
"""

from tsutae.skillchange.approve import approve_change, reject_change
from tsutae.skillchange.diff import set_version, unified
from tsutae.skillchange.editor import (
    EDITOR_ALLOWED_TOOLS,
    EDITOR_DISALLOWED_TOOLS,
    EDITOR_MAX_TURNS,
    SdkSkillEditor,
    SkillEditor,
    build_options,
    build_prompt,
    logging_to,
)
from tsutae.skillchange.errors import (
    BAD_REQUEST_CODES,
    NOT_FOUND_CODES,
    SERVER_ERROR_CODES,
    SkillChangeError,
    status_for,
)
from tsutae.skillchange.lock import LOCK_TIMEOUT_S, skill_lock
from tsutae.skillchange.service import MAX_REQUEST_CHARS, request_change

__all__ = [
    "BAD_REQUEST_CODES",
    "EDITOR_ALLOWED_TOOLS",
    "EDITOR_DISALLOWED_TOOLS",
    "EDITOR_MAX_TURNS",
    "LOCK_TIMEOUT_S",
    "MAX_REQUEST_CHARS",
    "NOT_FOUND_CODES",
    "SERVER_ERROR_CODES",
    "SdkSkillEditor",
    "SkillChangeError",
    "SkillEditor",
    "approve_change",
    "build_options",
    "build_prompt",
    "logging_to",
    "reject_change",
    "request_change",
    "set_version",
    "skill_lock",
    "status_for",
    "unified",
]

"""Skill の書き換え（D4）の例外。API は `code` を `{"error": code}` にする。

code と HTTP の対応（`status_for(code)`。API の router はこれを使う）:
- 400: invalid_name・invalid_request
- 404: unknown_skill・not_found
- 409: not_pending・not_ready・stale・busy（別の承認が進行中。依頼では同じ Skill の
  書き換えが作業中）・version_conflict・
  write_error ほか承認時の失敗
- 500: base_invalid（今の SKILL.md が壊れている）
"""

from __future__ import annotations

__all__ = [
    "BAD_REQUEST_CODES",
    "NOT_FOUND_CODES",
    "SERVER_ERROR_CODES",
    "SkillChangeError",
    "status_for",
]

BAD_REQUEST_CODES = frozenset({"invalid_name", "invalid_request"})
NOT_FOUND_CODES = frozenset({"unknown_skill", "not_found"})
SERVER_ERROR_CODES = frozenset({"base_invalid"})


class SkillChangeError(ValueError):
    """書き換えの依頼・承認・却下を受け付けられない。`code` は短い英字。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def status_for(code: str) -> int:
    """SkillChangeError の code に対応する HTTP の status。"""
    if code in BAD_REQUEST_CODES:
        return 400
    if code in NOT_FOUND_CODES:
        return 404
    if code in SERVER_ERROR_CODES:
        return 500
    return 409

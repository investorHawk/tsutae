"""D4 レジメンの会話の行（regimen_drafts.chat_json。T94）。文面は院内の画面にだけ出る。

- 先生の文: `{role: "doctor", text, generation, at}`
- Claude の返答: `{role: "assistant", text, changed: [欄の id], ask: {field_id, question,
  options} | null, proposed: [質問の key], reply_hidden, generation, at}`。返答の文に H1 が
  掛かれば text は `REPLY_HIDDEN`（固定の文）にし、reply_hidden を true にする
- 失敗: `{role: "system", kind: "turn_failed", reason, generation, at}`（T93 の回復の行と
  同じ形。reason は timeout・max_turns・max_budget・sdk_error・internal_error・
  cancelled・code_taken・invalid_result）

採用・破棄で chat_json は消える（T93）。
"""

from __future__ import annotations

from typing import Any

from tsutae.regimen.chat_types import AskOut

__all__ = [
    "REPLY_HIDDEN",
    "TURN_FAILED",
    "assistant_row",
    "doctor_row",
    "failed_row",
]

TURN_FAILED = "turn_failed"
REPLY_HIDDEN = (
    "（返答の文に個人を特定しうる表現の疑いがあったので表示しない。"
    "変えた欄は札のとおり）"
)


def doctor_row(text: str, generation: int, at: str) -> dict[str, Any]:
    return {"role": "doctor", "text": text, "generation": generation, "at": at}


def assistant_row(
    text: str,
    *,
    changed: tuple[str, ...],
    ask: AskOut | None,
    proposed: tuple[str, ...],
    reply_hidden: bool,
    generation: int,
    at: str,
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "text": text,
        "changed": list(changed),
        "ask": None if ask is None else ask.to_json(),
        "proposed": list(proposed),
        "reply_hidden": reply_hidden,
        "generation": generation,
        "at": at,
    }


def failed_row(reason: str, generation: int, at: str) -> dict[str, Any]:
    return {
        "role": "system",
        "kind": TURN_FAILED,
        "reason": reason,
        "generation": generation,
        "at": at,
    }

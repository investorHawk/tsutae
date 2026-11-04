"""質問の部品集（question_library。spec 9.1・docs/architecture.md §2・§9c）。

D4 レジメンの画面の小窓で選ぶ候補。SKILL.md・採用済みの版には影響しない（版は採用の
ときに短い名前・文を form JSON と questions_json に写して持つ）。

- 初期の6問（`SEED_QUESTIONS`）: 今の FOLFOX/CAPOX の質問。文と回答の型は SKILL.md の
  frontmatter、短い名前は医師画面の名前（`patient_strings.json` の `symptom.<key>` と同じ）。
  体温の質問は `fever` の1つだけ（38.0℃ の固定規則の対象。新しい下書きは初めから持つ）
- seed は `INSERT … ON CONFLICT DO NOTHING`（何度呼んでもよい。既にある行は変えない）
- 追加は書く前に全て検査する: key の形（`QUESTION_KEY_PATTERN`）・予約語、短い名前と文に
  フォームの質問と同じ `regimen.text_checks.text_issues`（長さ・改行や制御文字・`|`・
  薬の量。文は frontmatter のフロー形式に入れて YAML で読み戻せるか）と書式文字の拒否、
  回答の型は3択だけ（体温は seed の fever だけ）、H1（`detect_identifiers`。そのままの
  値と、依頼文に入る JSON の形の両方）
- 並びは入れた時刻の順。同じ時刻の中は初期の6問の順、その後は rowid（rowid だけには
  頼らない。VACUUM や表の作り直しで振り直されうる）
- 削除は選択肢から外すだけ（hidden=1。行は残すので、消した key は作り直せない）。
  初期の6問と、どれかの版（`skill_versions.questions_json`）が使っている key は消せない
- 入力の誤りは `QuestionInputError(code, field)`（API は 422）、重複・消せないは
  `QuestionConflictError(code)`（API は 409）、無い key は `NotFoundError`（404）
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from tsutae.config import now
from tsutae.db.connection import NotFoundError, dt_from_db, dt_to_db, write_transaction
from tsutae.masking import detect_identifiers
from tsutae.regimen.text_checks import FieldIssue, text_issues, yaml_issue
from tsutae.regimen.validate import key_yaml_checks
from tsutae.schemas import QUESTION_KEY_PATTERN

__all__ = [
    "ADDABLE_ORIGINS",
    "LABEL_MAX",
    "QuestionConflictError",
    "QuestionInputError",
    "RESERVED_KEYS",
    "SEED_QUESTIONS",
    "TEXT_MAX",
    "add_library_question",
    "get_library_question",
    "hide_library_question",
    "insert_question_row",
    "list_library_questions",
    "seed_question_library",
    "validate_library_question",
]

LABEL_MAX = 20  # regimen.validate.MAX_LABEL と同じ
TEXT_MAX = 200  # schemas.Question.text・regimen.validate.MAX_QUESTION_TEXT と同じ
ADDABLE_ORIGINS = frozenset({"doctor", "adopted"})
ADDABLE_ANSWER_TYPES = frozenset({"three_level"})
# 紙の経過表の体温の行の key（report.labels.TEMPERATURE_ROW_KEY）と取り違えないように
RESERVED_KEYS = frozenset({"temperature"})
_KEY_RE = re.compile(QUESTION_KEY_PATTERN)
_FORBIDDEN_CHARS = frozenset("|")
# H1 は _check_h1 で欄ごとに h1_blocked にする（JSON の形にも掛けるため）
_H1_ISSUE_CODE = "identifier"


def _seed(key: str, label: str, text: str, answer_type: str) -> Mapping[str, str]:
    return MappingProxyType(
        {"key": key, "label": label, "text": text, "answer_type": answer_type}
    )


# 並びは医師画面の列の順（frontend の answerLabels.ts の QUESTION_ORDER）
SEED_QUESTIONS: tuple[Mapping[str, str], ...] = (
    _seed(
        "numbness",
        "しびれ",
        "手足のしびれや冷たいものがさわりにくい感じはありましたか",
        "three_level",
    ),
    _seed("diarrhea", "下痢", "下痢はありましたか", "three_level"),
    _seed("stomatitis", "口内炎", "口の中の痛みや口内炎はありましたか", "three_level"),
    _seed(
        "nausea_appetite",
        "吐き気・食欲",
        "吐き気や食欲の落ち込みはありましたか",
        "three_level",
    ),
    _seed(
        "hand_foot",
        "手のひら・足の裏",
        "手のひらや足の裏の赤み・痛み・ひび割れはありましたか",
        "three_level",
    ),
    _seed("fever", "体温", "熱を測りましたか", "temperature"),
)

_COLUMNS = "key, label, text, answer_type, origin, hidden, created_at"
_SEED_RANK = {item["key"]: i for i, item in enumerate(SEED_QUESTIONS)}


class QuestionInputError(ValueError):
    """部品集に入れる値が検査に通らない（API は 422 `{error: code, field}`）。"""

    def __init__(self, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


class QuestionConflictError(Exception):
    """key の重複（key_taken）・消せない問（seed_question・in_use）。API は 409。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# 検査
# ---------------------------------------------------------------------------


def _has_bad_char(value: str) -> bool:
    """改行・タブ・制御文字・書式文字・`|` を含むか（表のセルと YAML の1行に入る）。"""
    return any(
        ch in _FORBIDDEN_CHARS or unicodedata.category(ch).startswith("C")
        for ch in value
    )


def _text_yaml_check(text: str) -> tuple[tuple[str, Any], ...]:
    """regimen.validate の questions.<row>.text と同じ frontmatter の断片。"""
    return (
        (
            f"- {{key: qkey, text: {text}, answer_type: three_level}}",
            [{"key": "qkey", "text": text, "answer_type": "three_level"}],
        ),
    )


def _form_issues(field: str, value: str) -> list[FieldIssue]:
    """フォームの質問の欄と同じ検査（H1 を除く）。"""
    if field == "text":
        issues = text_issues(
            field, value, max_len=TEXT_MAX, yaml_checks=_text_yaml_check(value)
        )
    else:
        issues = text_issues(field, value, max_len=LABEL_MAX)
    return [i for i in issues if i.code != _H1_ISSUE_CODE]


def _clean_line(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise QuestionInputError(f"invalid_{field}", field)
    cleaned = value.strip()
    if not cleaned or _has_bad_char(cleaned) or _form_issues(field, cleaned):
        raise QuestionInputError(f"invalid_{field}", field)
    return cleaned


def _check_key(key: object) -> str:
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
        raise QuestionInputError("invalid_key", "key")
    # フォームの questions.*.key と同じ検査（frontmatter で no・null 等が別の値に読まれる）
    if yaml_issue("key", key_yaml_checks(key)) is not None:
        raise QuestionInputError("invalid_key", "key")
    if key in RESERVED_KEYS:
        raise QuestionInputError("reserved_key", "key")
    return key


def _check_h1(fields: Mapping[str, str]) -> None:
    """そのままの値と、依頼文に入る JSON の形の両方に H1 の検出を掛ける。"""
    for field, value in fields.items():
        probe = json.dumps({field: value}, ensure_ascii=False)
        if detect_identifiers(value) or detect_identifiers(probe):
            raise QuestionInputError("h1_blocked", field)


def validate_library_question(
    *, key: object, label: object, text: object, answer_type: object = "three_level"
) -> dict[str, str]:
    """医師・採用から足す質問を検査し、整えた新しい dict を返す（引数は変えない）。"""
    checked_key = _check_key(key)
    cleaned = {
        "label": _clean_line(label, "label"),
        "text": _clean_line(text, "text"),
    }
    if not isinstance(answer_type, str) or answer_type not in ADDABLE_ANSWER_TYPES:
        raise QuestionInputError("invalid_answer_type", "answer_type")
    _check_h1({"key": checked_key, **cleaned})
    return {"key": checked_key, **cleaned, "answer_type": answer_type}


# ---------------------------------------------------------------------------
# 読み書き
# ---------------------------------------------------------------------------


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "label": row["label"],
        "text": row["text"],
        "answer_type": row["answer_type"],
        "origin": row["origin"],
        "hidden": bool(row["hidden"]),
        "created_at": dt_from_db(row["created_at"]),
    }


def insert_question_row(
    conn: sqlite3.Connection, item: Mapping[str, str], origin: str
) -> bool:
    """検査済みの1問を入れ、入れたら True。呼び出し側で write_transaction を開くこと。

    同じ key（外した問も）があれば何もせず False（確認と挿入を1文で行う）。
    """
    cur = conn.execute(
        f"INSERT INTO question_library ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, 0, ?)"
        " ON CONFLICT (key) DO NOTHING",
        (
            item["key"],
            item["label"],
            item["text"],
            item["answer_type"],
            origin,
            dt_to_db(now()),
        ),
    )
    return cur.rowcount > 0


def seed_question_library(conn: sqlite3.Connection) -> int:
    """初期の6問のうち無いものを入れ、入れた数を返す（既にある行は変えない）。"""
    with write_transaction(conn):
        return sum(insert_question_row(conn, item, "seed") for item in SEED_QUESTIONS)


def get_library_question(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    if not isinstance(key, str):
        return None
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM question_library WHERE key = ?", (key,)
    ).fetchone()
    return None if row is None else _row(row)


def list_library_questions(
    conn: sqlite3.Connection, *, include_hidden: bool = False
) -> list[dict[str, Any]]:
    """入れた順（初期の6問が先）。既定では外した問を含めない。

    created_at（JST の ISO 形式なので文字列の順＝時刻の順）で並べ、同じ時刻の中は
    初期の6問の順、その後は rowid（同じ時刻に入った追加の問の間だけ）。
    """
    where = "" if include_hidden else " WHERE hidden = 0"
    rows = conn.execute(
        f"SELECT rowid AS rid, {_COLUMNS} FROM question_library{where}"
    ).fetchall()
    ordered = sorted(
        rows,
        key=lambda r: (
            r["created_at"],
            _SEED_RANK.get(r["key"], len(_SEED_RANK)),
            r["rid"],
        ),
    )
    return [_row(r) for r in ordered]


def add_library_question(
    conn: sqlite3.Connection,
    *,
    key: str,
    label: str,
    text: str,
    answer_type: str = "three_level",
    origin: str = "doctor",
) -> dict[str, Any]:
    """検査して1問を足し、入れた行を返す。同じ key（外した問も）があれば key_taken。"""
    if not isinstance(origin, str) or origin not in ADDABLE_ORIGINS:
        raise QuestionInputError("invalid_origin", "origin")
    item = validate_library_question(
        key=key, label=label, text=text, answer_type=answer_type
    )
    with write_transaction(conn):
        if not insert_question_row(conn, item, origin):
            raise QuestionConflictError("key_taken")
    added = get_library_question(conn, item["key"])
    assert added is not None
    return added


def _used_by_a_version(conn: sqlite3.Connection, key: str) -> bool:
    """どれかの版の質問集に key があるか。読めない質問集は使っているとみなす。"""
    rows = conn.execute(
        "SELECT questions_json FROM skill_versions WHERE questions_json IS NOT NULL"
    ).fetchall()
    for row in rows:
        try:
            questions = json.loads(row["questions_json"])
        except (TypeError, ValueError):
            return True
        if not isinstance(questions, list):
            return True
        if any(isinstance(q, dict) and q.get("key") == key for q in questions):
            return True
    return False


def hide_library_question(conn: sqlite3.Connection, key: str) -> dict[str, Any]:
    """選択肢から外す（hidden=1。何度呼んでもよい）。外した後の行を返す。

    無い key は NotFoundError、初期の6問は seed_question、どれかの版が使っている key は
    in_use（どちらも QuestionConflictError）。確認と更新は同じトランザクションで行う。
    """
    with write_transaction(conn):
        found = get_library_question(conn, key)
        if found is None:
            raise NotFoundError("question not found")
        if found["origin"] == "seed":
            raise QuestionConflictError("seed_question")
        if _used_by_a_version(conn, found["key"]):
            raise QuestionConflictError("in_use")
        conn.execute(
            "UPDATE question_library SET hidden = 1 WHERE key = ?", (found["key"],)
        )
    hidden = get_library_question(conn, found["key"])
    assert hidden is not None
    return hidden

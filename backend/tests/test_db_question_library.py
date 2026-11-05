"""質問の部品集（question_library。spec 9.1・docs/architecture.md §2）。

- 初期の6問（今の FOLFOX/CAPOX の質問。文と型は SKILL.md、短い名前は医師画面の名前）
- seed は何度呼んでも重複しない
- 追加: key の形・重複（消した key も）・H1・改行や `|`・薬の量・YAML で読み戻せない文
  （フォームの質問と同じ検査）・体温の型を拒否
- 並びは入れた時刻の順（rowid に頼らない）
- 削除は選択肢から外すだけ（行は残す）。初期の6問と、どれかの版が使っている key は消せない
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tsutae.config import PATIENT_STRINGS_PATH
from tsutae.db import (
    NotFoundError,
    QuestionConflictError,
    QuestionInputError,
    add_library_question,
    connect,
    get_library_question,
    hide_library_question,
    init_db,
    list_library_questions,
    save_skill_version,
    seed_question_library,
)
from tsutae.db.repo_question_library import SEED_QUESTIONS, insert_question_row
from tsutae.regimen.text_checks import text_issues
from tsutae.schemas import Question
from tsutae.skills import load_skill

SEED_KEYS = [
    "numbness",
    "diarrhea",
    "stomatitis",
    "nausea_appetite",
    "hand_foot",
    "fever",
]


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    seed_question_library(c)
    return c


def _add(conn: sqlite3.Connection, **overrides: str) -> dict:
    fields = {
        "key": "fatigue",
        "label": "だるさ",
        "text": "だるさや疲れやすさはありましたか",
        "answer_type": "three_level",
        **overrides,
    }
    return add_library_question(conn, **fields)


def _row_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM question_library").fetchone()[0]


# --- 初期の6問 ---------------------------------------------------------------


def test_seed_inserts_six_questions_in_order(conn: sqlite3.Connection) -> None:
    items = list_library_questions(conn)
    assert [q["key"] for q in items] == SEED_KEYS
    assert all(q["origin"] == "seed" for q in items)
    assert all(q["hidden"] is False for q in items)


def test_seed_text_and_type_match_current_skills() -> None:
    by_key: dict[str, Question] = {}
    for name in ("regimen-folfox", "regimen-capox"):
        for q in load_skill(name).questions:
            assert by_key.setdefault(q.key, q) == q  # 2本で同じ key は同じ文
    assert sorted(by_key) == sorted(SEED_KEYS)
    for item in SEED_QUESTIONS:
        assert item["text"] == by_key[item["key"]].text
        assert item["answer_type"] == by_key[item["key"]].answer_type


def test_seed_labels_are_doctor_screen_names() -> None:
    strings = json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))
    labels = {item["key"]: item["label"] for item in SEED_QUESTIONS}
    assert labels == {k: strings[f"symptom.{k}"] for k in SEED_KEYS}
    assert labels["hand_foot"] == "手のひら・足の裏"
    assert labels["fever"] == "体温"


def test_fever_is_the_only_temperature_question() -> None:
    temps = [i["key"] for i in SEED_QUESTIONS if i["answer_type"] == "temperature"]
    assert temps == ["fever"]


def test_seed_is_idempotent(conn: sqlite3.Connection) -> None:
    assert seed_question_library(conn) == 0
    init_db(conn)
    assert seed_question_library(conn) == 0
    assert _row_count(conn) == 6


def test_seed_on_fresh_db_returns_count(tmp_db_path: Path) -> None:
    c = connect(tmp_db_path)
    init_db(c)
    assert seed_question_library(c) == 6
    assert seed_question_library(c) == 0


def test_seed_does_not_overwrite_existing_row(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE question_library SET label = 'x' WHERE key = 'diarrhea'")
    conn.commit()
    seed_question_library(conn)
    assert get_library_question(conn, "diarrhea")["label"] == "x"


# --- 追加 ---------------------------------------------------------------------


def test_add_question_is_listed_after_seed(conn: sqlite3.Connection) -> None:
    added = _add(conn)
    assert added["key"] == "fatigue"
    assert added["origin"] == "doctor"
    assert added["hidden"] is False
    keys = [q["key"] for q in list_library_questions(conn)]
    assert keys == [*SEED_KEYS, "fatigue"]


def test_add_strips_label_and_text(conn: sqlite3.Connection) -> None:
    added = _add(conn, label="  だるさ ", text=" だるさはありましたか　")
    assert added["label"] == "だるさ"
    assert added["text"] == "だるさはありましたか"


def test_add_with_adopted_origin(conn: sqlite3.Connection) -> None:
    added = _add(conn, origin="adopted")
    assert added["origin"] == "adopted"


def test_add_rejects_unknown_origin(conn: sqlite3.Connection) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, origin="seed")
    assert err.value.code == "invalid_origin"
    assert _row_count(conn) == 6


def test_add_rejects_duplicate_key(conn: sqlite3.Connection) -> None:
    _add(conn)
    with pytest.raises(QuestionConflictError) as err:
        _add(conn, label="べつ", text="べつの文はありましたか")
    assert err.value.code == "key_taken"
    assert get_library_question(conn, "fatigue")["label"] == "だるさ"


def test_add_rejects_seed_key(conn: sqlite3.Connection) -> None:
    with pytest.raises(QuestionConflictError) as err:
        _add(conn, key="diarrhea")
    assert err.value.code == "key_taken"


def test_hidden_key_cannot_be_recreated(conn: sqlite3.Connection) -> None:
    _add(conn)
    hide_library_question(conn, "fatigue")
    with pytest.raises(QuestionConflictError) as err:
        _add(conn)
    assert err.value.code == "key_taken"
    assert get_library_question(conn, "fatigue")["hidden"] is True


@pytest.mark.parametrize(
    "key",
    [
        "",
        "a",
        "Fatigue",
        "1fatigue",
        "_fatigue",
        "fa-tigue",
        "fa tigue",
        "だるさ",
        "fatigue\n",
        "a" * 42,
    ],
)
def test_add_rejects_bad_key_shape(conn: sqlite3.Connection, key: str) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, key=key)
    assert (err.value.code, err.value.field) == ("invalid_key", "key")


@pytest.mark.parametrize("key", ["no", "yes", "on", "off", "null", "true", "false"])
def test_add_rejects_key_that_yaml_reads_back_differently(
    conn: sqlite3.Connection, key: str
) -> None:
    """フォームの questions.*.key と同じく、frontmatter で読み戻せない key は入れない。"""
    with pytest.raises(QuestionInputError) as err:
        _add(conn, key=key)
    assert (err.value.code, err.value.field) == ("invalid_key", "key")


def test_add_rejects_reserved_key(conn: sqlite3.Connection) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, key="temperature")
    assert (err.value.code, err.value.field) == ("reserved_key", "key")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", ""),
        ("label", "   "),
        ("label", "あ" * 21),
        ("label", "だる\nさ"),
        ("label", "だる|さ"),
        ("label", "だる\tさ"),
        ("text", ""),
        ("text", "あ" * 201),
        ("text", "だるさは\nありましたか"),
        ("text", "だるさ|ありましたか"),
        ("text", "だるさ\x00ありましたか"),
    ],
)
def test_add_rejects_bad_label_or_text(
    conn: sqlite3.Connection, field: str, value: str
) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, **{field: value})
    assert (err.value.code, err.value.field) == (f"invalid_{field}", field)
    assert _row_count(conn) == 6


# フォームの質問の検査（regimen.validate の questions.<row>.text）と同じ規則
_FORM_REJECTED_TEXTS = [
    "1日2g飲みましたか",  # dose
    "ロキソニン60mgを飲みましたか",  # dose
    "質問: だるさはありましたか",  # yaml（': '）
    "だるさ, 疲れはありましたか",  # yaml（','）
    "だるさ #ありましたか",  # yaml（' #'）
    "{だるさ}はありましたか",  # yaml（'{' '}'）
    "'だるさ'はありましたか",  # yaml（引用符）
    "*だるさはありましたか",  # yaml（先頭の '*'）
    "null",
    "123",
    "yes",
]


@pytest.mark.parametrize("value", _FORM_REJECTED_TEXTS)
def test_add_rejects_text_the_form_rejects(
    conn: sqlite3.Connection, value: str
) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, text=value)
    assert (err.value.code, err.value.field) == ("invalid_text", "text")
    assert _row_count(conn) == 6


@pytest.mark.parametrize("value", ["2g", "60mgの薬"])
def test_add_rejects_dose_in_label(conn: sqlite3.Connection, value: str) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, label=value)
    assert (err.value.code, err.value.field) == ("invalid_label", "label")


@pytest.mark.parametrize("item", SEED_QUESTIONS, ids=lambda i: i["key"])
def test_seed_questions_pass_the_form_checks(item: dict) -> None:
    text = item["text"]
    fragment = f"- {{key: qkey, text: {text}, answer_type: three_level}}"
    expected = [{"key": "qkey", "text": text, "answer_type": "three_level"}]
    issues = list(
        text_issues("t", text, max_len=200, yaml_checks=((fragment, expected),))
    )
    assert issues == []
    assert list(text_issues("l", item["label"], max_len=20)) == []


@pytest.mark.parametrize("value", [None, 1, b"fatigue"])
def test_add_rejects_non_str(conn: sqlite3.Connection, value: object) -> None:
    with pytest.raises(QuestionInputError):
        add_library_question(
            conn,
            key=value,  # type: ignore[arg-type]
            label="だるさ",
            text="だるさはありましたか",
        )


@pytest.mark.parametrize("answer_type", ["temperature", "yes_no", ""])
def test_add_accepts_only_three_level(
    conn: sqlite3.Connection, answer_type: str
) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, answer_type=answer_type)
    assert err.value.field == "answer_type"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key", "q_meal2"),  # id_like（skillchange.check の既知の例）
        ("label", "磯鷲さん"),
        ("text", "磯鷲さんにもらった薬は飲みましたか"),
        ("text", "電話 0312345678 にかけましたか"),
    ],
)
def test_add_rejects_h1_detection(
    conn: sqlite3.Connection, field: str, value: str
) -> None:
    with pytest.raises(QuestionInputError) as err:
        _add(conn, **{field: value})
    assert (err.value.code, err.value.field) == ("h1_blocked", field)
    assert _row_count(conn) == 6


def test_add_does_not_mutate_or_keep_input(conn: sqlite3.Connection) -> None:
    added = _add(conn)
    added["label"] = "かえた"
    assert get_library_question(conn, "fatigue")["label"] == "だるさ"


def test_insert_question_row_skips_existing_key(conn: sqlite3.Connection) -> None:
    item = {"key": "diarrhea", "label": "x", "text": "x", "answer_type": "three_level"}
    with conn:
        assert insert_question_row(conn, item, "doctor") is False
    assert get_library_question(conn, "diarrhea")["label"] == "下痢"
    assert _row_count(conn) == 6


# --- 並び ---------------------------------------------------------------------


def test_list_order_does_not_depend_on_rowid(conn: sqlite3.Connection) -> None:
    _add(conn)
    # 表を作り直した・VACUUM の後のように rowid の順が入れた順とずれても並びは変わらない
    with conn:
        row = conn.execute(
            "SELECT * FROM question_library WHERE key = 'numbness'"
        ).fetchone()
        conn.execute("DELETE FROM question_library WHERE key = 'numbness'")
        conn.execute(
            "INSERT INTO question_library (key, label, text, answer_type, origin,"
            " hidden, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            tuple(row),
        )
    keys = [q["key"] for q in list_library_questions(conn)]
    assert keys == [*SEED_KEYS, "fatigue"]


def test_list_order_with_same_created_at_follows_seed_order(
    conn: sqlite3.Connection,
) -> None:
    _add(conn)
    with conn:
        conn.execute(
            "UPDATE question_library SET created_at = '2026-11-09T10:00:00.000000+09:00'"
        )
        conn.execute("UPDATE question_library SET rowid = 1000 - rowid")
    keys = [q["key"] for q in list_library_questions(conn)]
    assert keys == [*SEED_KEYS, "fatigue"]


# --- 削除（選択肢から外す） -------------------------------------------------


def test_hide_removes_from_list_but_keeps_row(conn: sqlite3.Connection) -> None:
    _add(conn)
    hidden = hide_library_question(conn, "fatigue")
    assert hidden["hidden"] is True
    assert "fatigue" not in [q["key"] for q in list_library_questions(conn)]
    all_keys = [q["key"] for q in list_library_questions(conn, include_hidden=True)]
    assert "fatigue" in all_keys
    assert _row_count(conn) == 7


def test_hide_is_idempotent(conn: sqlite3.Connection) -> None:
    _add(conn)
    hide_library_question(conn, "fatigue")
    assert hide_library_question(conn, "fatigue")["hidden"] is True


@pytest.mark.parametrize("key", SEED_KEYS)
def test_seed_questions_cannot_be_hidden(conn: sqlite3.Connection, key: str) -> None:
    with pytest.raises(QuestionConflictError) as err:
        hide_library_question(conn, key)
    assert err.value.code == "seed_question"
    assert get_library_question(conn, key)["hidden"] is False


def test_key_used_by_a_version_cannot_be_hidden(conn: sqlite3.Connection) -> None:
    _add(conn)
    questions = [
        Question(key="fatigue", text="だるさはありましたか", answer_type="three_level"),
        Question(key="fever", text="熱を測りましたか", answer_type="temperature"),
    ]
    save_skill_version(conn, "regimen-ram-wptx", 1, "---\n", questions)
    with pytest.raises(QuestionConflictError) as err:
        hide_library_question(conn, "fatigue")
    assert err.value.code == "in_use"
    assert get_library_question(conn, "fatigue")["hidden"] is False


def test_versions_without_questions_do_not_block(conn: sqlite3.Connection) -> None:
    _add(conn)
    save_skill_version(conn, "report-format-default", 1, "---\n", None)
    assert hide_library_question(conn, "fatigue")["hidden"] is True


def test_hide_unknown_key_is_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        hide_library_question(conn, "fatigue")


def test_get_unknown_key_is_none(conn: sqlite3.Connection) -> None:
    assert get_library_question(conn, "fatigue") is None
    assert get_library_question(conn, 1) is None  # type: ignore[arg-type]


# --- 表の制約 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [("answer_type", "yes_no"), ("origin", "ai"), ("hidden", 2)],
)
def test_table_checks_reject_unknown_values(
    conn: sqlite3.Connection, column: str, value: object
) -> None:
    row = {
        "key": "fatigue",
        "label": "だるさ",
        "text": "だるさはありましたか",
        "answer_type": "three_level",
        "origin": "doctor",
        "hidden": 0,
        "created_at": "2026-11-09T10:00:00.000000+09:00",
        column: value,
    }
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO question_library (key, label, text, answer_type, origin,"
            " hidden, created_at) VALUES (:key, :label, :text, :answer_type,"
            " :origin, :hidden, :created_at)",
            row,
        )

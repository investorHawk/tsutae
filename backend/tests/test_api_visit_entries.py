"""`POST /api/visit` の本文の entries（plan-device-records §5.5）。

スマホに置いた記録が受付のときだけ届く。外からの入力なので全て検査し、1件でも不正なら全体を
422 にして何も保存しない。同じ ID は二重にならない。本文は 5MB まで（超えたら 413）。
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from api_helpers import add_entry, add_patient, api_client, db_conn, register
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.api.body_limit import DEFAULT_BODY_MAX_BYTES
from tsutae.api.visit_entries import MAX_VISIT_ENTRIES, VISIT_BODY_MAX_BYTES
from tsutae.schemas import EntryCreate, Question

# 第2コースの Day1（2026-10-13）〜今日（2026-11-09）が範囲
C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
SKILL = "regimen-folfox@1"


def _at(day: str = "2026-11-09", clock: str = "20:15:00.000000") -> str:
    return f"{day}T{clock}+09:00"


def _entry(client_id: str = UUID_A, day: str = "2026-11-09", **over: Any) -> dict:
    base = {
        "client_entry_id": client_id,
        "recorded_at": _at(day),
        "record_date": day,
        "kind": "mixed",
        "by_proxy": False,
        "skill_version": SKILL,
        "answers": [
            {"question_key": "fever", "value": "measured", "temperature": 38.2},
            {"question_key": "diarrhea", "value": "present", "temperature": None},
        ],
        "free_text": "（合成）だるい",
    }
    return {**base, **over}


def _too_sick(client_id: str = UUID_A, day: str = "2026-11-09", **over: Any) -> dict:
    return _entry(client_id, day, kind="too_sick", answers=[], free_text=None, **over)


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C3)
    assert register(client, patient_id).status_code == 200
    return patient_id


def _post(client: TestClient, entries: list[dict], no: str = "A-023") -> Any:
    return client.post("/api/visit", json={"reception_no": no, "entries": entries})


def _saved(client: TestClient, pid: str) -> list[Any]:
    with db_conn(client.app) as conn:
        return db.list_entries(conn, pid)


def _visits(client: TestClient) -> list[dict[str, Any]]:
    with db_conn(client.app) as conn:
        return db.list_visits(conn)


def _assert_refused(r: Any, client: TestClient, pid: str, code="invalid_input") -> None:
    assert r.status_code == 422, r.text
    assert r.json() == {"error": code}
    assert _saved(client, pid) == []
    assert _visits(client) == []


# ---------------------------------------------------------------------------
# 受け取る
# ---------------------------------------------------------------------------


def test_entries_are_saved_with_the_visit(client: TestClient, pid: str) -> None:
    r = _post(client, [_entry(), _too_sick(UUID_B, "2026-10-13")])
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message_key": "visit.done"}
    assert len(_visits(client)) == 1
    older, newer = _saved(client, pid)
    assert (older.kind, str(older.record_date)) == ("too_sick", "2026-10-13")
    assert newer.kind == "mixed"
    assert newer.free_text == "（合成）だるい"
    assert newer.skill_version == SKILL
    assert [a.question_key for a in newer.answers] == ["fever", "diarrhea"]
    assert newer.answers[0].temperature == 38.2


def test_visit_without_entries_still_works(client: TestClient, pid: str) -> None:
    assert client.post("/api/visit", json={"reception_no": "A-1"}).status_code == 200
    assert _post(client, [], no="A-2").status_code == 200
    assert len(_visits(client)) == 2


def test_resend_does_not_double_entries_or_visit(client: TestClient, pid: str) -> None:
    assert _post(client, [_entry()]).status_code == 200
    calls = client.app.state.runner_factory.calls
    r = _post(client, [_entry()])
    assert r.status_code == 200
    assert len(_saved(client, pid)) == 1
    assert len(_visits(client)) == 1
    assert client.app.state.runner_factory.calls == calls  # 生成も起動しない


def test_resend_with_a_new_record_adds_only_the_new_one(
    client: TestClient, pid: str
) -> None:
    assert _post(client, [_entry()]).status_code == 200
    assert _post(client, [_entry(), _too_sick(UUID_B)]).status_code == 200
    assert len(_saved(client, pid)) == 2
    assert len(_visits(client)) == 1


def test_demo_id_is_accepted(client: TestClient, pid: str) -> None:
    assert _post(client, [_entry("demo-12")]).status_code == 200
    assert len(_saved(client, pid)) == 1


def test_window_edges_are_accepted(client: TestClient, pid: str) -> None:
    edges = [_too_sick(UUID_A, "2026-10-13"), _too_sick(UUID_B, "2026-11-09")]
    assert _post(client, edges).status_code == 200


def test_first_course_window_starts_at_its_day1(client: TestClient) -> None:
    first = add_patient(client.app, courses=[(1, date(2026, 11, 1))])
    assert register(client, first).status_code == 200
    assert _post(client, [_too_sick(day="2026-11-01")]).status_code == 200
    r = _post(client, [_too_sick(UUID_B, "2026-10-31")], no="A-9")
    assert r.status_code == 422


def test_received_entry_does_not_write_a_mark(client: TestClient, pid: str) -> None:
    assert _post(client, [_entry(day="2026-11-01")]).status_code == 200
    with db_conn(client.app) as conn:
        assert db.marked_patients(conn, date(2026, 11, 1)) == set()


def test_no_course_is_409(client: TestClient) -> None:
    none = add_patient(client.app)
    assert register(client, none).status_code == 200
    r = _post(client, [_entry()])
    assert r.status_code == 409
    assert r.json() == {"error": "no_course"}
    assert _saved(client, none) == []


def test_without_cookie_is_401(client: TestClient, pid: str) -> None:
    client.cookies.clear()
    assert _post(client, [_entry()]).status_code == 401
    assert _saved(client, pid) == []


# ---------------------------------------------------------------------------
# 断る（1件でも不正なら全体を 422 にして何も保存しない）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "day", ["2026-10-12", "2026-09-27", "2026-11-10", "2027-01-01"]
)
def test_record_date_outside_the_window_is_refused(
    client: TestClient, pid: str, day: str
) -> None:
    _assert_refused(_post(client, [_too_sick(UUID_B), _too_sick(day=day)]), client, pid)


def test_record_date_must_match_recorded_at(client: TestClient, pid: str) -> None:
    body = _entry(record_date="2026-11-08")
    _assert_refused(_post(client, [body]), client, pid)


def test_record_date_is_read_in_jst(client: TestClient, pid: str) -> None:
    """UTC で書かれた時刻でも、記録日は JST の日付で比べる。"""
    body = _entry(recorded_at="2026-11-08T15:30:00+00:00", record_date="2026-11-09")
    assert _post(client, [body]).status_code == 200
    assert str(_saved(client, pid)[0].record_date) == "2026-11-09"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "abc",
        "demo-",
        "demo-1x",
        "DEMO-1",
        "demo-1\n",
        "11111111-1111-4111-8111-11111111111",
        "11111111-1111-4111-8111-111111111111\n",
        "11111111-1111-4111-8111-11111111111G",
        "11111111111141118111111111111111",
        "../../etc/passwd",
    ],
)
def test_bad_client_entry_id_is_refused(client: TestClient, pid: str, bad: str) -> None:
    _assert_refused(_post(client, [_entry(bad)]), client, pid)


def test_duplicate_id_in_one_body_is_refused(client: TestClient, pid: str) -> None:
    _assert_refused(_post(client, [_entry(), _too_sick()]), client, pid)


def test_too_many_entries_are_refused(client: TestClient, pid: str) -> None:
    body = [_too_sick(str(uuid.uuid4())) for _ in range(MAX_VISIT_ENTRIES + 1)]
    _assert_refused(_post(client, body), client, pid)


def test_limit_of_entries_is_accepted(client: TestClient, pid: str) -> None:
    body = [_too_sick(str(uuid.uuid4())) for _ in range(MAX_VISIT_ENTRIES)]
    assert MAX_VISIT_ENTRIES == 500
    assert _post(client, body).status_code == 200
    assert len(_saved(client, pid)) == MAX_VISIT_ENTRIES


@pytest.mark.parametrize(
    "over",
    [
        {"answers": [{"question_key": "unknown_question", "value": "none"}]},
        {
            "answers": [
                {"question_key": "diarrhea", "value": "measured", "temperature": 38}
            ]
        },
        {"answers": [{"question_key": "diarrhea", "value": "not_measured"}]},
        {"answers": [{"question_key": "fever", "value": "none"}]},
        {"answers": [{"question_key": "fever", "value": "measured"}]},
        {
            "answers": [
                {"question_key": "fever", "value": "measured", "temperature": 99}
            ]
        },
        {"answers": [{"question_key": "diarrhea", "value": "none", "temperature": 37}]},
        {"answers": "x"},
    ],
)
def test_bad_answers_are_refused(
    client: TestClient, pid: str, over: dict[str, Any]
) -> None:
    good = _too_sick(UUID_B)
    bad = _entry(**{**{"free_text": None, "kind": "answers"}, **over})
    _assert_refused(_post(client, [good, bad]), client, pid)


@pytest.mark.parametrize(
    "over",
    [
        {"kind": "answers"},  # 自由記載もあるので mixed
        {"kind": "too_sick"},
        {"kind": "other"},
        {"kind": "too_sick", "answers": [], "free_text": "（合成）だるい"},
        {"kind": "answers", "answers": [], "free_text": None},
        {"skill_version": "regimen-folfox@77"},
        {"skill_version": "regimen-capox@1"},  # この患者のレジメンではない
        {"skill_version": "report-format-default@1"},
        {"skill_version": "regimen-folfox"},
        {"skill_version": "@1"},
        {"recorded_at": "2026-11-09T20:15:00"},  # 時差なし
        {"recorded_at": "x"},
        {"record_date": "x"},
        {"by_proxy": "x"},
        {"pid": "P-AAAAAAAA"},  # 知らない項目
        {"question_text": "x"},
    ],
)
def test_bad_fields_are_refused(
    client: TestClient, pid: str, over: dict[str, Any]
) -> None:
    _assert_refused(_post(client, [_entry(**over)]), client, pid)


def test_question_text_copy_is_not_accepted_in_answers(
    client: TestClient, pid: str
) -> None:
    """質問の文の写しは端末にだけ置く（送る前に端末が外す）。"""
    answer = {"question_key": "diarrhea", "value": "none", "question_text": "x"}
    body = _entry(kind="answers", answers=[answer], free_text=None)
    _assert_refused(_post(client, [body]), client, pid)


def test_free_text_too_long_has_its_own_code(client: TestClient, pid: str) -> None:
    body = _entry(free_text="あ" * 2001)
    _assert_refused(_post(client, [body]), client, pid, code="free_text_too_long")


def test_answers_are_checked_against_the_version_of_the_record(
    client: TestClient, pid: str
) -> None:
    """古い版の記録は古い版の質問集で照らす（今の版ではない）。"""
    old = [Question(key="old_question", text="古い質問", answer_type="three_level")]
    with db_conn(client.app) as conn:
        db.save_skill_version(conn, "regimen-folfox", 99, "（版99）", old)
    answer = {"question_key": "old_question", "value": "hard"}
    good = _entry(
        kind="answers",
        answers=[answer],
        free_text=None,
        skill_version="regimen-folfox@99",
    )
    now_version = {**good, "skill_version": SKILL}
    today_question = {"question_key": "diarrhea", "value": "none"}
    new_on_old = {**good, "answers": [today_question]}
    _assert_refused(_post(client, [now_version]), client, pid)
    _assert_refused(_post(client, [new_on_old]), client, pid)
    assert _post(client, [good]).status_code == 200
    assert _saved(client, pid)[0].skill_version == "regimen-folfox@99"


def test_existing_rows_are_kept_when_refused(client: TestClient, pid: str) -> None:
    add_entry(client.app, pid, EntryCreate(free_text="（合成）前の記録"))
    assert _post(client, [_too_sick(day="2026-01-01")]).status_code == 422
    assert len(_saved(client, pid)) == 1
    assert _visits(client) == []


# ---------------------------------------------------------------------------
# 本文の大きさ
# ---------------------------------------------------------------------------


def _json_headers() -> dict[str, str]:
    return {"content-type": "application/json"}


def test_body_over_the_limit_is_413(client: TestClient, pid: str) -> None:
    assert VISIT_BODY_MAX_BYTES == 5 * 1024 * 1024
    big = b" " * (VISIT_BODY_MAX_BYTES + 1)
    r = client.post("/api/visit", content=big, headers=_json_headers())
    assert r.status_code == 413
    assert r.json() == {"error": "body_too_large"}
    assert _visits(client) == []


def test_chunked_body_over_the_limit_is_413(client: TestClient, pid: str) -> None:
    """Content-Length が無くても、読んだ量で断る。"""

    def chunks() -> Any:
        yield b" " * VISIT_BODY_MAX_BYTES
        yield b" "

    r = client.post("/api/visit", content=chunks(), headers=_json_headers())
    assert r.status_code == 413
    assert _visits(client) == []


def test_valid_entries_over_the_limit_are_413(client: TestClient, pid: str) -> None:
    """件数の検査より先に、本文の大きさで断る。"""
    entry = _entry(free_text="あ" * 2000)
    entries = [{**entry, "client_entry_id": str(uuid.uuid4())} for _ in range(900)]
    body = json.dumps({"reception_no": "A-1", "entries": entries}, ensure_ascii=False)
    assert len(body.encode()) > VISIT_BODY_MAX_BYTES
    r = client.post("/api/visit", content=body.encode(), headers=_json_headers())
    assert r.status_code == 413
    assert _saved(client, pid) == []


def test_body_at_the_limit_goes_on_to_validation(client: TestClient, pid: str) -> None:
    padded = json.dumps({"reception_no": "A-1"}).encode()
    padded += b" " * (VISIT_BODY_MAX_BYTES - len(padded))
    r = client.post("/api/visit", content=padded, headers=_json_headers())
    assert r.status_code == 200
    assert len(_visits(client)) == 1


def test_full_size_records_fit_the_limit(client: TestClient, pid: str) -> None:
    """件数の上限ちょうどで全て最大の長さでも、本文の上限に収まる（断るのは異常な本文だけ）。"""
    day = "2026-11-09"
    entries = [
        _entry(str(uuid.uuid4()), day, free_text="あ" * 2000)
        for _ in range(MAX_VISIT_ENTRIES)
    ]
    body = json.dumps({"reception_no": "A-1", "entries": entries}, ensure_ascii=False)
    assert len(body.encode()) < VISIT_BODY_MAX_BYTES


def test_other_routes_use_the_default_limit(client: TestClient) -> None:
    """5MB は受付だけ。他の経路は既定の上限（test_api_body_limit）。"""
    big = b" " * (DEFAULT_BODY_MAX_BYTES + 1)
    r = client.post("/api/patient/register", content=big, headers=_json_headers())
    assert r.status_code == 413
    ok = b" " * (DEFAULT_BODY_MAX_BYTES + 1)
    r = client.post("/api/visit", content=ok, headers=_json_headers())
    assert r.status_code == 422

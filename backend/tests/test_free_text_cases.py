"""端末が保存した自由記載を受付が断らないこと（plan-device-records §5.5）。

記録はスマホに置くので、記録のときにサーバーの検査を通らない。画面が通したのに受付が断ると、
その1件のせいで受診の全体が 422 になり、以後ずっと送れない。画面（`cleanFreeText`）と同じ表
（frontend/src/test/fixtures/free_text_cases.json）で、画面が保存する形を受付が受け取ることを
確かめる。expected は画面が保存する自由記載（null は記録しない）。server_raw は「サーバーも
生の入力を同じ形にする」。false の行は画面だけが落とす（生のまま届けば受付が断るか残す）。
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from api_helpers import add_patient, api_client, db_conn, register
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tsutae import db
from tsutae.api.visit_entries import VisitEntryIn
from tsutae.schemas import ClosedAnswer, EntryCreate

CASES: list[dict[str, Any]] = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "frontend/src/test/fixtures/free_text_cases.json"
    ).read_text(encoding="utf-8")
)
RAW_CASES = [c for c in CASES if c["server_raw"]]
ANSWER = ClosedAnswer(question_key="diarrhea", value="present")
AT = "2026-11-09T20:15:00.000000+09:00"
DAY = "2026-11-09"
SKILL = "regimen-folfox@1"
UUID_A = "11111111-1111-4111-8111-111111111111"


def _body(free_text: str | None, *, kind: str, answers: list[Any]) -> dict[str, Any]:
    return {
        "client_entry_id": UUID_A,
        "recorded_at": AT,
        "record_date": DAY,
        "kind": kind,
        "by_proxy": False,
        "skill_version": SKILL,
        "answers": answers,
        "free_text": free_text,
    }


def _name(case: dict[str, Any]) -> str:
    return case["name"]


@pytest.mark.parametrize("case", [c for c in CASES if c["expected"]], ids=_name)
def test_what_the_phone_saves_alone_is_accepted(case: dict[str, Any]) -> None:
    expected = case["expected"]
    entry = VisitEntryIn(**_body(expected, kind="free_text", answers=[]))
    assert entry.as_entry().free_text == expected


@pytest.mark.parametrize("case", CASES, ids=_name)
def test_what_the_phone_saves_with_an_answer_is_accepted(case: dict[str, Any]) -> None:
    expected = case["expected"]
    kind = "answers" if expected is None else "mixed"
    entry = VisitEntryIn(**_body(expected, kind=kind, answers=[ANSWER]))
    assert entry.as_entry().free_text == expected
    assert entry.as_entry().kind == kind


@pytest.mark.parametrize("case", RAW_CASES, ids=_name)
def test_server_makes_the_raw_input_the_same(case: dict[str, Any]) -> None:
    created = EntryCreate(answers=[ANSWER], free_text=case["input"])
    assert created.free_text == case["expected"]


@pytest.mark.parametrize(
    "case", [c for c in RAW_CASES if c["expected"] is None], ids=_name
)
def test_server_refuses_the_raw_input_the_phone_does_not_save(
    case: dict[str, Any],
) -> None:
    """表の null はサーバーでも空の記録（画面が通すと全体が 422 になる）。"""
    with pytest.raises(ValidationError):
        VisitEntryIn(**_body(case["input"], kind="free_text", answers=[]))


def test_table_has_every_python_space() -> None:
    """画面の空白の一覧が Python の str.strip とずれたら、この行で気づく。"""
    every = {chr(c) for c in range(sys.maxunicode + 1) if chr(c).isspace()}
    assert any(set(c["input"]) == every for c in CASES)


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=[(1, date(2026, 10, 27))])
    assert register(client, patient_id).status_code == 200
    return patient_id


def test_visit_accepts_everything_the_phone_saves(client: TestClient, pid: str) -> None:
    answer = {"question_key": "diarrhea", "value": "present", "temperature": None}
    entries = []
    for case in CASES:
        expected = case["expected"]
        kind = "answers" if expected is None else "mixed"
        entries.append(
            {
                **_body(expected, kind=kind, answers=[answer]),
                "client_entry_id": str(uuid.uuid4()),
            }
        )
    r = client.post("/api/visit", json={"reception_no": "A-023", "entries": entries})
    assert r.status_code == 200, r.text
    with db_conn(client.app) as conn:
        assert len(db.list_entries(conn, pid)) == len(CASES)


def test_visit_refuses_a_lone_surrogate_so_the_phone_must_drop_it(
    client: TestClient, pid: str
) -> None:
    """ブラウザの JSON.stringify は片割れを \\ud83d の形で送る。json.dumps も同じ形にする。"""
    body = _body("だるい\ud83d", kind="free_text", answers=[])
    r = client.post(
        "/api/visit",
        content=json.dumps({"reception_no": "A-023", "entries": [body]}),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422, r.text
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []

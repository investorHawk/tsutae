"""受付の費用の歯止め: 1人の患者が1日に開ける受診の数（plan-device-records §6）。症例は全て合成。

自動の変換し直しは1受診3回までなので、受診の数を抑えれば、番号を変えて送り続けても1人の患者の
1日の変換の回数に上限ができる。正しい番号での送り直しと、家族の記録は止めない。Claude は呼ばない。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from api_helpers import add_patient, api_client, db_conn, login_doctor, register
from fastapi.testclient import TestClient
from test_api_second_device import (
    ALREADY_PRINTED,
    C3,
    UUID_A,
    _events,
    _factory,
    _post,
    _too_sick,
)

from tsutae import db
from tsutae.config import now, today

TOO_MANY = {"error": "too_many_visits"}


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        login_doctor(c)
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C3)
    assert register(client, patient_id).status_code == 200
    return patient_id


def _uuid(n: int) -> str:
    return f"{n:08x}-1111-4111-8111-111111111111"


def _fill_numbers(client: TestClient) -> None:
    """上限まで別の番号で受付する（どれも記録つき）。"""
    for n in range(db.MAX_OPEN_VISITS_PER_DAY):
        body = [_too_sick(_uuid(n))]
        assert _post(client, body, no=f"X-{n}").status_code == 200


def _visit_count(client: TestClient) -> int:
    with db_conn(client.app) as conn:
        return len(db.list_visits(conn))


def test_a_new_number_over_the_limit_is_refused_and_saves_nothing(
    client: TestClient, pid: str
) -> None:
    _fill_numbers(client)
    factory = _factory(client)
    calls = factory.calls
    with db_conn(client.app) as conn:
        kept = len(db.list_entries(conn, pid))

    r = _post(client, [_too_sick(UUID_A)], no="X-OVER")

    assert (r.status_code, r.json()) == (409, TOO_MANY)
    assert factory.calls == calls
    assert _visit_count(client) == db.MAX_OPEN_VISITS_PER_DAY
    with db_conn(client.app) as conn:
        assert len(db.list_entries(conn, pid)) == kept


def test_a_number_already_open_is_still_received_at_the_limit(
    client: TestClient, pid: str
) -> None:
    """家族のスマホが同じ番号で送る分は止めない（§6）。"""
    _fill_numbers(client)
    factory = _factory(client)
    calls = factory.calls

    assert _post(client, [_too_sick(UUID_A)], no="X-0").status_code == 200

    assert factory.calls > calls
    assert _visit_count(client) == db.MAX_OPEN_VISITS_PER_DAY
    with db_conn(client.app) as conn:
        kept = conn.execute(
            "SELECT 1 FROM entries WHERE client_entry_id = ?", (UUID_A,)
        ).fetchall()
    assert len(kept) == 1


def test_changing_the_number_again_and_again_has_an_upper_bound_of_runs(
    client: TestClient, pid: str
) -> None:
    """番号を変えて送り続けても、1人の患者の1日の変換は「受診の数 × (1 + 自動の回数)」まで。"""
    factory = _factory(client)
    statuses = [
        _post(client, [_too_sick(_uuid(n))], no=f"X-{n}").status_code
        for n in range(db.MAX_OPEN_VISITS_PER_DAY * 4)
    ]
    assert statuses.count(200) == db.MAX_OPEN_VISITS_PER_DAY
    assert statuses.count(409) == db.MAX_OPEN_VISITS_PER_DAY * 3
    # 開いている番号へ新しい記録を送り続けても、それ以上は増えない
    for n in range(db.REGEN_AUTO_MAX * db.MAX_OPEN_VISITS_PER_DAY):
        assert _post(client, [_too_sick(_uuid(100 + n))], no="X-0").status_code == 200
    assert factory.calls == db.MAX_OPEN_VISITS_PER_DAY * (1 + db.REGEN_AUTO_MAX)
    # architecture と repo_visits の説明に書いた数字（5 ×（1 + 3））
    assert factory.calls == 20


def test_refused_visit_logs_nothing_on_the_open_rows(
    client: TestClient, pid: str
) -> None:
    _fill_numbers(client)
    with db_conn(client.app) as conn:
        rows = db.list_visits(conn)
    before = {v["id"]: len(_events(client, v["id"])) for v in rows}
    assert _post(client, [_too_sick(UUID_A)], no="X-OVER").status_code == 409
    assert {v["id"]: len(_events(client, v["id"])) for v in rows} == before


def test_printed_today_comes_before_the_limit(client: TestClient, pid: str) -> None:
    """今日の印刷済みがあれば、その案内を出す。"""
    _fill_numbers(client)
    with db_conn(client.app) as conn:
        first = db.list_visits(conn)[0]["id"]
    assert client.post(f"/api/doctor/visits/{first}/printed").status_code == 200
    r = _post(client, [_too_sick(UUID_A)], no="X-OVER")
    assert (r.status_code, r.json()) == (409, ALREADY_PRINTED)


def test_other_patients_are_not_counted(client: TestClient, pid: str) -> None:
    _fill_numbers(client)
    other = add_patient(client.app, courses=C3)
    assert register(client, other).status_code == 200
    assert _post(client, [_too_sick(UUID_A)], no="X-OVER").status_code == 200


def test_other_days_are_not_counted(client: TestClient, pid: str) -> None:
    yesterday = today() - timedelta(days=1)
    with db_conn(client.app) as conn:
        for n in range(db.MAX_OPEN_VISITS_PER_DAY):
            db.create_visit(
                conn, pid, f"Y-{n}", yesterday, now() + timedelta(days=1), 3
            )
    assert _post(client, [_too_sick(UUID_A)], no="X-0").status_code == 200

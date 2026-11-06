"""2台目のスマホ（plan-device-records §6）の API の動き。症例は全て合成。Claude は呼ばない。

- 新しい記録が届くと統合して変換し直す（生成中は終わってから1回だけ）。番号を間違えて別の
  受診ができても、その日の開いた受診はどちらも全ての記録で変換する
- 新しい記録が無ければ何もしない
- 自動は1受診3回まで。超えたら記録だけ受け取り、D3 に出し、医師が押せる
- 今日の印刷済みの受診があれば、どの番号でも 409 already_printed（何も保存しない）
- 生成中は印刷できない。doctor_masks は統合の後も entry_id で効く
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import (
    RunnerFactory,
    add_patient,
    api_client,
    db_conn,
    login_doctor,
    register,
    seed_synthetic,
)
from e2e_scripts import InterruptingRunner
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner
from test_api_doctor_masks import _item, _ready_visit, _runner, _save

from tsutae import db
from tsutae.api import orphans, visit
from tsutae.config import now, today
from tsutae.masking import GENERIC_MASK
from tsutae.pipeline import service
from tsutae.schemas import EntryCreate

DEMO = "P-DEMO0001"
C3 = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
SKILL = "regimen-folfox@1"
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
UUID_C = "33333333-3333-4333-8333-333333333333"
TEXT_A = "（合成）だるい"
TEXT_B = "（合成）家族のスマホの記録"
ALREADY_PRINTED = {"error": "already_printed"}


def _too_sick(client_id: str) -> dict[str, Any]:
    return {
        "client_entry_id": client_id,
        "recorded_at": "2026-11-09T08:15:00.000000+09:00",
        "record_date": "2026-11-09",
        "kind": "too_sick",
        "by_proxy": False,
        "skill_version": SKILL,
        "answers": [],
        "free_text": None,
    }


def _text(client_id: str, text: str, by_proxy: bool = False) -> dict[str, Any]:
    return {
        **_too_sick(client_id),
        "kind": "free_text",
        "free_text": text,
        "by_proxy": by_proxy,
    }


def _received(client_id: str, text: str) -> db.ReceivedEntry:
    return db.ReceivedEntry(
        client_entry_id=client_id,
        entry=EntryCreate(free_text=text),
        recorded_at=datetime.fromisoformat("2026-11-09T08:15:00+09:00"),
        skill_version=SKILL,
    )


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


def _post(client: TestClient, entries: list[dict], no: str = "A-023") -> Any:
    return client.post("/api/visit", json={"reception_no": no, "entries": entries})


def _use(client: TestClient, runner: Any) -> RunnerFactory:
    factory = RunnerFactory(runner)
    client.app.state.runner_factory = factory
    return factory


def _factory(client: TestClient) -> RunnerFactory:
    return client.app.state.runner_factory


def _only_visit(client: TestClient) -> dict[str, Any]:
    with db_conn(client.app) as conn:
        (only,) = db.list_visits(conn)
    return only


def _row(client: TestClient) -> dict[str, Any]:
    """D3 の行（GET /api/doctor/visits）。"""
    (row,) = client.get("/api/doctor/visits").json()["visits"]
    return row


def _events(client: TestClient, vid: int) -> list[dict[str, Any]]:
    with db_conn(client.app) as conn:
        return db.list_pipeline_logs(conn, "visit", vid)


def _once(job: Callable[[], None]) -> Callable[[], None]:
    """生成は何度も回るので、1回目の中でだけ job を呼ぶ。"""
    done: list[bool] = []

    def run() -> None:
        if not done:
            done.append(True)
            job()

    return run


def _add_from_other_phone(client: TestClient, pid: str, *items: Any) -> Callable:
    """生成の途中で、別の端末の受付が届く（別の接続で）。1回目の生成の中でだけ呼ぶ。"""

    def add() -> None:
        with db_conn(client.app) as conn:
            for item in items:
                receipt = db.create_visit_once(
                    conn,
                    pid,
                    "A-023",
                    today(),
                    now() + timedelta(hours=24),
                    3,
                    (item,),
                )
                assert receipt.regenerate is False

    return _once(add)


# ---------------------------------------------------------------------------
# 統合して変換し直す
# ---------------------------------------------------------------------------


def test_new_records_on_a_ready_visit_are_converted_again(
    client: TestClient, pid: str
) -> None:
    runner = FakeRunner()
    factory = _use(client, runner)
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert _only_visit(client)["status"] == "ready"
    assert factory.calls == 1
    assert TEXT_B not in runner.prompts[0]

    r = _post(client, [_text(UUID_B, TEXT_B, by_proxy=True)])
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message_key": "visit.done"}

    only = _only_visit(client)
    assert factory.calls == 2
    assert (only["status"], only["regen_count"]) == ("ready", 1)
    assert only["regen_pending"] is False
    assert TEXT_A in runner.prompts[1] and TEXT_B in runner.prompts[1]
    with db_conn(client.app) as conn:
        kept = db.list_entries(conn, pid)
    assert sorted(e.free_text for e in kept) == sorted([TEXT_A, TEXT_B])
    assert [e.by_proxy for e in kept if e.free_text == TEXT_B] == [True]


def test_the_ai_result_is_also_converted_again(client: TestClient, pid: str) -> None:
    """記録が増えたときだけ、AI の結果の ready も通す。"""
    factory = _factory(client)
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    only = _only_visit(client)
    assert (only["status"], only["fallback"]) == ("ready", False)
    assert client.post(f"/api/doctor/visits/{only['id']}/regenerate").status_code == 409
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    assert factory.calls == 2
    assert _only_visit(client)["regen_count"] == 1


def test_failed_visit_is_converted_again(client: TestClient, pid: str) -> None:
    factory = _factory(client)
    with db_conn(client.app) as conn:
        vid = db.create_visit(conn, pid, "A-023", today(), now() + timedelta(days=1), 3)
        db.set_visit_status(conn, vid, "failed")
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    assert factory.calls == 1
    only = _only_visit(client)
    assert (only["id"], only["status"], only["regen_count"]) == (vid, "ready", 1)


@pytest.mark.parametrize("status", ["ready", "failed"])
def test_resend_without_new_records_does_nothing(
    client: TestClient, pid: str, status: str
) -> None:
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    before = _only_visit(client)
    if status == "failed":
        with db_conn(client.app) as conn:
            db.set_visit_status(conn, before["id"], "failed")
        before = _only_visit(client)
    factory = _factory(client)
    calls = factory.calls
    for body in ([_too_sick(UUID_A)], []):
        assert _post(client, body).status_code == 200
    assert factory.calls == calls
    assert _only_visit(client) == before
    assert "regenerate_requested" not in [
        e["event"] for e in _events(client, before["id"])
    ]


def _visit_of(client: TestClient, number: str) -> dict[str, Any]:
    with db_conn(client.app) as conn:
        (found,) = [v for v in db.list_visits(conn) if v["reception_no"] == number]
    return found


def test_wrong_number_is_a_second_row_and_each_uses_all_records(
    client: TestClient, pid: str
) -> None:
    runner = FakeRunner()
    factory = _use(client, runner)
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert _post(client, [_text(UUID_B, TEXT_B)], no="A-999").status_code == 200
    with db_conn(client.app) as conn:
        first, second = db.list_visits(conn)
    assert (first["reception_no"], second["reception_no"]) == ("A-023", "A-999")
    assert (first["status"], second["status"]) == ("ready", "ready")
    # 新しい行の1回目と、前の行の変換し直し。前の行だけが回数を使う
    assert (first["regen_count"], second["regen_count"]) == (1, 0)
    assert factory.calls == 3
    assert TEXT_B not in runner.prompts[0]
    for prompt in runner.prompts[1:]:
        assert TEXT_A in prompt and TEXT_B in prompt


def test_fixing_a_wrong_number_leaves_the_right_row_with_the_record(
    client: TestClient, pid: str
) -> None:
    """番号を間違えた後で直しても、正しい番号の紙に記録が載り、D3 に札が出る。"""
    assert client.post(f"/api/patient/{pid}/record-marks").status_code == 200
    factory = _use(client, FakeRunner())
    assert _post(client, []).status_code == 200
    vid = _visit_of(client, "A-023")["id"]
    with db_conn(client.app) as conn:
        assert db.get_report(conn, vid)[1].header.not_received_days == 1

    assert _post(client, [_too_sick(UUID_B)], no="A-999").status_code == 200
    with db_conn(client.app) as conn:
        assert db.get_report(conn, vid)[1].header.not_received_days == 0
    calls = factory.calls

    r = _post(client, [_too_sick(UUID_B)])
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message_key": "visit.done"}
    assert factory.calls == calls
    rows = client.get("/api/doctor/visits").json()["visits"]
    assert [(v["reception_no"], v["status"], v["regen_count"]) for v in rows] == [
        ("A-023", "ready", 1),
        ("A-999", "ready", 0),
    ]


def test_wrong_number_logs_the_regeneration_only_on_the_row_that_ran_again(
    client: TestClient, pid: str
) -> None:
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert _post(client, [_text(UUID_B, TEXT_B)], no="A-999").status_code == 200
    first = _visit_of(client, "A-023")["id"]
    second = _visit_of(client, "A-999")["id"]
    logged = [e for e in _events(client, first) if e["event"] == "regenerate_requested"]
    assert [e["decision"] for e in logged] == ["added_records"]
    assert "regenerate_requested" not in [e["event"] for e in _events(client, second)]


def test_new_record_on_an_existing_number_logs_every_row_that_runs_again(
    client: TestClient, pid: str
) -> None:
    """既存の番号へ送ると別の番号の開いた行も動く。動く行は全て同じログを持つ（§6）。"""
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert _post(client, [_text(UUID_A, TEXT_A)], no="A-999").status_code == 200
    first = _visit_of(client, "A-023")["id"]
    second = _visit_of(client, "A-999")["id"]
    for vid in (first, second):
        assert "regenerate_requested" not in [e["event"] for e in _events(client, vid)]

    assert _post(client, [_text(UUID_B, TEXT_B)]).status_code == 200

    for vid in (first, second):
        logged = [
            e for e in _events(client, vid) if e["event"] == "regenerate_requested"
        ]
        assert [e["decision"] for e in logged] == ["added_records"]


def test_wrong_number_while_the_first_is_generating_runs_it_once_more(
    client: TestClient, pid: str
) -> None:
    def add() -> None:
        with db_conn(client.app) as conn:
            db.create_visit_once(
                conn,
                pid,
                "A-999",
                today(),
                now() + timedelta(hours=24),
                3,
                (_received(UUID_B, TEXT_B),),
            )

    inner = FakeRunner()
    factory = _use(client, InterruptingRunner(inner, _once(add)))
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert factory.calls == 2
    assert TEXT_B in inner.prompts[1]
    first = _visit_of(client, "A-023")
    assert (first["status"], first["regen_pending"], first["regen_count"]) == (
        "ready",
        False,
        1,
    )


def test_regeneration_is_logged_without_text(client: TestClient, pid: str) -> None:
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert _post(client, [_text(UUID_B, TEXT_B)]).status_code == 200
    logs = _events(client, _only_visit(client)["id"])
    names = [log["event"] for log in logs]
    assert names.count("regenerate_requested") == 1
    assert names.count("run_start") == 2
    assert names.index("regenerate_requested") > names.index("visit_ready")
    assert names.index("regenerate_requested") < len(names) - names[::-1].index(
        "run_start"
    )
    (requested,) = [log for log in logs if log["event"] == "regenerate_requested"]
    assert requested["decision"] == "added_records"
    for key in ("hook_name", "agent_type", "tool_name"):
        assert requested[key] is None
    assert not any(TEXT_B in str(log) for log in logs)


def test_not_received_day_is_filled_by_the_other_phone(
    client: TestClient, pid: str
) -> None:
    """本人のスマホに無い日は紙で「届いていない」。家族のスマホの記録が届けば消える。"""
    assert client.post(f"/api/patient/{pid}/record-marks").status_code == 200
    assert _post(client, []).status_code == 200
    vid = _only_visit(client)["id"]
    with db_conn(client.app) as conn:
        assert db.get_report(conn, vid)[1].header.not_received_days == 1
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    with db_conn(client.app) as conn:
        assert db.get_report(conn, vid)[1].header.not_received_days == 0


def test_d3_row_tells_the_regeneration(client: TestClient, pid: str) -> None:
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    row = _row(client)
    assert (row["regen_pending"], row["regen_count"]) == (False, 0)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    row = _row(client)
    assert (row["regen_pending"], row["regen_count"]) == (False, 1)


# ---------------------------------------------------------------------------
# 生成中に追加
# ---------------------------------------------------------------------------


def test_addition_while_generating_runs_once_more_after_it_ends(
    client: TestClient, pid: str
) -> None:
    inner = FakeRunner()
    add = _add_from_other_phone(client, pid, _received(UUID_B, TEXT_B))
    runner = InterruptingRunner(inner, add)
    factory = _use(client, runner)
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert factory.calls == 2
    assert TEXT_B in inner.prompts[1]
    only = _only_visit(client)
    assert (only["status"], only["regen_pending"], only["regen_count"]) == (
        "ready",
        False,
        1,
    )
    logged = [
        e for e in _events(client, only["id"]) if e["event"] == "regenerate_requested"
    ]
    assert [e["decision"] for e in logged] == ["added_records"]


def test_many_additions_while_generating_run_only_once_more(
    client: TestClient, pid: str
) -> None:
    add = _add_from_other_phone(
        client, pid, _received(UUID_B, TEXT_B), _received(UUID_C, TEXT_B + "2")
    )
    factory = _use(client, InterruptingRunner(FakeRunner(), add))
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert factory.calls == 2
    assert _only_visit(client)["regen_count"] == 1


def test_additions_in_every_run_stop_at_the_automatic_limit(
    client: TestClient, pid: str
) -> None:
    """どの回の最中に届いても次の回へ回る。費用の歯止めはループの単位で止まる。"""
    sent: list[str] = []

    def add_a_new_record() -> None:
        client_id = f"b{len(sent)}111111-1111-4111-8111-111111111111"
        sent.append(client_id)
        with db_conn(client.app) as conn:
            receipt = db.create_visit_once(
                conn,
                pid,
                "A-023",
                today(),
                now() + timedelta(hours=24),
                3,
                (_received(client_id, TEXT_B),),
            )
        assert receipt.regenerate is False

    factory = _use(client, InterruptingRunner(FakeRunner(), add_a_new_record))
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert factory.calls == 1 + db.REGEN_AUTO_MAX
    only = _only_visit(client)
    assert (only["status"], only["regen_pending"], only["regen_count"]) == (
        "ready",
        True,
        db.REGEN_AUTO_MAX,
    )


def _generating_visit(client: TestClient, pid: str) -> int:
    with db_conn(client.app) as conn:
        return db.create_visit(
            conn, pid, "A-023", today(), now() + timedelta(days=1), 3
        )


def test_post_while_generating_only_sets_the_flag_then_run_consumes_it(
    client: TestClient, pid: str
) -> None:
    vid = _generating_visit(client, pid)
    factory = _factory(client)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    assert factory.calls == 0
    only = _only_visit(client)
    assert (only["status"], only["regen_pending"]) == ("generating", True)
    settings = client.app.state.settings
    asyncio.run(visit.run_generation(settings, factory, vid))
    assert factory.calls == 2
    only = _only_visit(client)
    assert (only["status"], only["regen_pending"], only["regen_count"]) == (
        "ready",
        False,
        1,
    )


def test_failed_run_with_pending_runs_once_more(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = _generating_visit(client, pid)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    real = service.generate_visit_report
    rounds: list[str] = []

    async def fail_first(conn: sqlite3.Connection, visit_id: int, **kw: Any) -> None:
        rounds.append("run")
        if len(rounds) == 1:
            raise RuntimeError("boom")
        await real(conn, visit_id, **kw)

    monkeypatch.setattr(service, "generate_visit_report", fail_first)
    settings = client.app.state.settings
    asyncio.run(visit.run_generation(settings, _factory(client), vid))
    assert rounds == ["run", "run"]
    assert _only_visit(client)["status"] == "ready"


def test_db_error_on_taking_does_not_leave_generating(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = _generating_visit(client, pid)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200

    def broken(conn: sqlite3.Connection, visit_id: int, **kw: Any) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "take_regen_pending", broken)
    settings = client.app.state.settings
    asyncio.run(visit.run_generation(settings, _factory(client), vid))
    only = _only_visit(client)
    assert (only["status"], only["regen_pending"]) == ("failed", True)


def test_orphan_with_pending_does_not_call_claude(client: TestClient, pid: str) -> None:
    runner = FakeRunner()
    factory = _use(client, runner)
    _generating_visit(client, pid)
    assert _post(client, [_text(UUID_B, TEXT_B)]).status_code == 200
    settings = client.app.state.settings
    assert asyncio.run(orphans.recover_orphans(settings)) == 1
    assert (factory.calls, runner.calls) == (0, 0)
    only = _only_visit(client)
    assert (only["status"], only["fallback"]) == ("ready", True)
    assert only["regen_pending"] is False


# ---------------------------------------------------------------------------
# 自動の上限
# ---------------------------------------------------------------------------


def _use_up_automatic_runs(client: TestClient) -> None:
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    for n in range(db.REGEN_AUTO_MAX):
        body = [_too_sick(f"a{n}111111-1111-4111-8111-111111111111")]
        assert _post(client, body).status_code == 200
    assert _only_visit(client)["regen_count"] == db.REGEN_AUTO_MAX


def test_over_the_limit_only_receives_and_the_doctor_can_press(
    client: TestClient, pid: str
) -> None:
    factory = _factory(client)
    _use_up_automatic_runs(client)
    assert factory.calls == 4

    r = _post(client, [_too_sick(UUID_B)])
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message_key": "visit.done"}
    assert factory.calls == 4
    with db_conn(client.app) as conn:
        ids = conn.execute(
            "SELECT 1 FROM entries WHERE client_entry_id = ?", (UUID_B,)
        ).fetchall()
    assert len(ids) == 1
    row = _row(client)
    assert (row["status"], row["regen_pending"], row["regen_count"]) == (
        "ready",
        True,
        db.REGEN_AUTO_MAX,
    )

    url = f"/api/doctor/visits/{row['id']}/regenerate"
    assert client.post(url).status_code == 200
    assert factory.calls == 5
    row = _row(client)
    assert (row["status"], row["regen_pending"], row["regen_count"]) == (
        "ready",
        False,
        db.REGEN_AUTO_MAX,
    )
    # 追加の記録を入れ終えたので、AI の結果の ready はまた押せない
    assert client.post(url).status_code == 409


def test_resend_over_the_limit_without_new_records_sets_nothing(
    client: TestClient, pid: str
) -> None:
    _use_up_automatic_runs(client)
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    assert _row(client)["regen_pending"] is False


def test_print_over_the_limit_is_allowed_and_clears_the_records(
    client: TestClient, pid: str
) -> None:
    """医師は D3 の「追加の記録あり」を見たうえで、そのまま印刷することもできる。"""
    _use_up_automatic_runs(client)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    vid = _row(client)["id"]
    assert client.post(f"/api/doctor/visits/{vid}/printed").status_code == 200
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []


# ---------------------------------------------------------------------------
# 印刷済み
# ---------------------------------------------------------------------------


def _print(client: TestClient, vid: int) -> None:
    assert client.post(f"/api/doctor/visits/{vid}/printed").status_code == 200


@pytest.mark.parametrize("number", ["A-023", "A-999", "　Ａ－０２３ "])
def test_printed_today_is_refused_for_every_number(
    client: TestClient, pid: str, number: str
) -> None:
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200
    vid = _only_visit(client)["id"]
    _print(client, vid)
    factory = _factory(client)
    calls = factory.calls

    r = _post(client, [_text(UUID_B, TEXT_B)], no=number)
    assert r.status_code == 409
    assert r.json() == ALREADY_PRINTED
    assert factory.calls == calls
    assert _only_visit(client)["status"] == "printed"
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []
    assert "regenerate_requested" not in [e["event"] for e in _events(client, vid)]


def _open_two_numbers(client: TestClient) -> dict[str, int]:
    """番号を間違えて2行できた受診（印刷すると受付番号が消えるので、先に控える）。"""
    assert _post(client, [_too_sick(UUID_A)], no="A-023").status_code == 200
    assert _post(client, [], no="A-999").status_code == 200
    with db_conn(client.app) as conn:
        return {v["reception_no"]: v["id"] for v in db.list_visits(conn)}


@pytest.mark.parametrize(
    ("printed", "still_open"), [("A-999", "A-023"), ("A-023", "A-999")]
)
@pytest.mark.parametrize(
    "entries",
    [
        pytest.param([_text(UUID_B, TEXT_B)], id="new_record"),
        pytest.param([_too_sick(UUID_A)], id="resent_record"),
        pytest.param([], id="no_records"),
    ],
)
def test_printed_today_is_refused_for_a_number_still_open(
    client: TestClient,
    pid: str,
    printed: str,
    still_open: str,
    entries: list[dict[str, Any]],
) -> None:
    """もう片方の行は開いたまま。受け取ると、先に渡した紙に載らない記録が「届いた」になる（§6）。

    開いた行が残るので、受付で受け取った記録は印刷の後も消えない。
    """
    ids = _open_two_numbers(client)
    _print(client, ids[printed])
    factory = _factory(client)
    calls = factory.calls
    row = _row(client)
    assert row["reception_no"] == still_open
    assert row["status"] == "ready"
    events = _events(client, ids[still_open])
    with db_conn(client.app) as conn:
        kept = db.list_entries(conn, pid)
    assert len(kept) == 1

    r = _post(client, entries, no=still_open)

    assert (r.status_code, r.json()) == (409, ALREADY_PRINTED)
    assert factory.calls == calls
    assert _row(client) == row
    assert _events(client, ids[still_open]) == events
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == kept


def test_printed_is_refused_without_records_too(client: TestClient, pid: str) -> None:
    """1台の患者も変わる（同じ日の2回目の受診は受付で扱う）。"""
    assert client.post("/api/visit", json={"reception_no": "A-1"}).status_code == 200
    _print(client, _only_visit(client)["id"])
    r = client.post("/api/visit", json={"reception_no": "A-2"})
    assert (r.status_code, r.json()) == (409, ALREADY_PRINTED)


def test_printed_yesterday_is_not_refused(client: TestClient, pid: str) -> None:
    yesterday = today() - timedelta(days=1)
    with db_conn(client.app) as conn:
        vid = db.create_visit(
            conn, pid, "A-023", yesterday, now() + timedelta(days=1), 3
        )
        db.mark_printed(conn, vid)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200


def test_print_while_converting_again_is_refused(
    client: TestClient, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """変換のし直しの最中は前のレポートを出さず、印刷済みにもしない。"""
    assert _post(client, [_too_sick(UUID_A)]).status_code == 200

    async def not_yet(*args: Any) -> None:
        return None

    monkeypatch.setattr(visit, "run_generation", not_yet)
    assert _post(client, [_too_sick(UUID_B)]).status_code == 200
    vid = _only_visit(client)["id"]
    assert _only_visit(client)["status"] == "generating"
    assert client.get(f"/api/doctor/visits/{vid}/report").status_code == 404
    r = client.post(f"/api/doctor/visits/{vid}/printed")
    assert (r.status_code, r.json()) == (409, {"error": "generating"})
    assert _only_visit(client)["status"] == "generating"
    with db_conn(client.app) as conn:
        assert len(db.list_entries(conn, pid)) == 2


def test_print_in_the_middle_of_a_run_with_pending_is_not_revived(
    client: TestClient, pid: str
) -> None:
    """生成の途中で閉じた受診は、待っている分があっても開き直さない。"""

    def add_then_print() -> None:
        with db_conn(client.app) as conn:
            db.create_visit_once(
                conn,
                pid,
                "A-023",
                today(),
                now() + timedelta(days=1),
                3,
                (_received(UUID_B, TEXT_B),),
            )
            (only,) = db.list_visits(conn)
            assert db.mark_printed(conn, only["id"])

    factory = _use(client, InterruptingRunner(FakeRunner(), add_then_print))
    assert _post(client, [_text(UUID_A, TEXT_A)]).status_code == 200
    assert factory.calls == 1
    only = _only_visit(client)
    assert (only["status"], only["reception_no"]) == ("printed", None)
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []
        assert db.get_report(conn, only["id"]) is None


# ---------------------------------------------------------------------------
# doctor_masks
# ---------------------------------------------------------------------------


def test_doctor_masks_still_apply_after_records_are_merged(
    tmp_path: Path, fixed_today: str
) -> None:
    with api_client(tmp_path) as client:
        assert DEMO in seed_synthetic(client.app)
        login_doctor(client)
        vid = _ready_visit(client)
        assert _save(client, vid, _item()).status_code == 200
        with db_conn(client.app) as conn:
            before = db.list_doctor_masks(conn, vid)
        assert list(before) == [38]

        runner = _runner(before)
        _use(client, runner)
        added = _text(UUID_B, TEXT_B)
        assert _post(client, [added]).status_code == 200

        assert runner.calls == 1
        assert GENERIC_MASK + "さんにもらった漢方" in runner.prompts[0]
        assert "磯鷲" not in runner.prompts[0]
        assert TEXT_B in runner.prompts[0]
        with db_conn(client.app) as conn:
            only = db.get_visit(conn, vid)
            assert db.list_doctor_masks(conn, vid) == before
            timeline = db.get_timeline(conn, vid)
        assert (only["status"], only["regen_count"]) == ("ready", 1)
        assert timeline is not None
        assert 38 not in [u.entry_id for u in timeline.unprocessed_entries]

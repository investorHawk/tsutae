"""スマホ保存の通し（plan-device-records §2）。ポートを開かず、TestClient と偽の runner で。

登録 → 毎日の印（本文なし）→ 端末の形の記録を受付で送る → D3 に ready → 紙に今コースの Day と
「届いていない日」→ 印刷済み（または 24 時間）で受付の記録が DB のどこにも残らない。印は残るので、
Web Push の判定は同じ印を見続ける。見本は test_device_records_seed.py。

端末の記録は画面（frontend の toDeviceEntry・toVisitEntry）と同じ形を、印の応答から作る。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import (
    FakePushSender,
    add_patient,
    api_client,
    db_conn,
    login_doctor,
    register,
)
from claude_agent_sdk import ClaudeAgentOptions
from e2e_scripts import grid_row, prompt_input
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner, standard_steps
from push_helpers import SECOND_ENDPOINT, subscription_body, vapid_overrides

from tsutae import db
from tsutae.api import app as app_module
from tsutae.config import JST, now
from tsutae.pipeline.tools import RunCollector
from tsutae.push.dispatch import PushCounts, send_due_once
from tsutae.schemas import Course, RunStats

# C3 は 10/27 が Day1、11/09 が Day14 で受診日（fixed_today）。範囲は C2 の Day1（10/13）から
COURSES = [(1, date(2026, 9, 27)), (2, date(2026, 10, 13)), (3, date(2026, 10, 27))]
RECEPTION = "A-023"
TODAY = "2026-11-09"
QUOTE = "（合成）夜からおなかがゆるくなった"
PREVIOUS_COURSE_NOTE = "（合成）前のコースの日のメモ"
TODAY_NOTE = "（合成）今朝は落ち着いている"
# 消えたあとに DB のどの表にも残らないはずの文字
SECRETS = (QUOTE, PREVIOUS_COURSE_NOTE, TODAY_NOTE)
# 日付の印を付ける日のうち、受付で届かない日（別の端末で書いた・端末の記録が消えた）
LOST_IN_C3 = "2026-11-05"  # Day10
LOST_IN_C2 = "2026-10-21"
MARKED_DAYS = {
    "2026-10-20",
    LOST_IN_C2,
    "2026-11-01",
    "2026-11-02",
    LOST_IN_C3,
    TODAY,
}
EVENING = datetime(2026, 11, 9, 20, 5, tzinfo=JST)


def _per_symptom(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "term": event["term"],
        "question_key": event["question_key"],
        "start_day": event["day"],
        "start_date": event["date"],
        "representative_quote": event["source_quote"],
        "confidence": event["confidence"],
    }


class _PromptRunner(FakeRunner):
    """送られた入力を読んで台本を作る runner（記録の数も番号も入力で決まるので、先に書けない）。"""

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        parsed = prompt_input(prompt)
        events = [
            {
                "entry_no": e["entry_no"],
                "date": e["record_date"],
                "day": e["day"],
                "course_no": parsed["schedule"]["course_no"],
                "term": "下痢",
                "question_key": "diarrhea",
                "status": "present",
                "source_quote": e["masked_free_text"],
                "confidence": 0.9,
                "by_proxy": e["by_proxy"],
            }
            for e in parsed["entries"]
            if e["masked_free_text"] == QUOTE
        ]
        self.steps = tuple(
            standard_steps(
                {"events": events, "contradictions": []},
                {"per_symptom": [_per_symptom(e) for e in events]},
            )
        )
        return await super().run(prompt, options, collector)


@contextmanager
def _patient_client(tmp_path: Path, **overrides: Any) -> Iterator[TestClient]:
    with api_client(tmp_path, runner=_PromptRunner(), **overrides) as client:
        login_doctor(client)
        yield client


def _new_patient(client: TestClient) -> str:
    pid = add_patient(client.app, courses=COURSES)
    assert register(client, pid).status_code == 200
    return pid


class _Phone:
    """1台のスマホ。その日のサーバーの時計で印を付け、画面と同じ形の記録を端末に置く。"""

    def __init__(self, client: TestClient, pid: str, mp: pytest.MonkeyPatch) -> None:
        self.client = client
        self.pid = pid
        self.mp = mp
        self.entries: dict[str, dict[str, Any]] = {}

    def record(
        self,
        day: str,
        *,
        answers: list[dict[str, Any]] | None = None,
        free_text: str | None = None,
        too_sick: bool = False,
    ) -> dict[str, Any]:
        """GET questions → POST record-marks（本文なし）→ 端末に保存。"""
        self.mp.setenv("TSUTAE_TODAY", day)
        url = f"/api/patient/{self.pid}"
        questions = self.client.get(f"{url}/questions").json()
        assert questions["today"] == day
        mark = self.client.post(f"{url}/record-marks")
        assert mark.status_code == 200, mark.text
        assert mark.json()["record_date"] == day
        self.mp.setenv("TSUTAE_TODAY", TODAY)
        answered = answers or []
        entry = {
            "client_entry_id": str(uuid.uuid4()),
            "recorded_at": mark.json()["recorded_at"],
            "record_date": mark.json()["record_date"],
            "kind": _kind(answered, free_text, too_sick),
            "by_proxy": False,
            "skill_version": questions["skill_version"],
            "answers": answered,
            "free_text": free_text,
        }
        self.entries[day] = entry
        return entry

    def record_course(self) -> None:
        """前コースと今コースに記録する。LOST_IN_* の日は印だけが届く記録になる。"""
        diarrhea = {"question_key": "diarrhea", "value": "hard", "temperature": None}
        fever = {"question_key": "fever", "value": "measured", "temperature": 37.2}
        self.record("2026-10-20", free_text=PREVIOUS_COURSE_NOTE)
        self.record(LOST_IN_C2, too_sick=True)
        self.record("2026-11-01", answers=[diarrhea], free_text=QUOTE)
        self.record("2026-11-02", too_sick=True)
        self.record(LOST_IN_C3, answers=[fever])
        self.record(TODAY, answers=[fever], free_text=TODAY_NOTE)

    def visit_body(self, reception_no: str = RECEPTION) -> dict[str, Any]:
        lost = {LOST_IN_C2, LOST_IN_C3}
        sent = [e for day, e in self.entries.items() if day not in lost]
        return {"reception_no": reception_no, "entries": sent}

    def send_visit(self, reception_no: str = RECEPTION) -> None:
        r = self.client.post("/api/visit", json=self.visit_body(reception_no))
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "message_key": "visit.done"}


def _kind(answers: list[dict[str, Any]], free_text: str | None, too_sick: bool) -> str:
    if too_sick:
        return "too_sick"
    if answers and free_text:
        return "mixed"
    return "answers" if answers else "free_text"


def _d3_row(client: TestClient, reception_no: str = RECEPTION) -> dict[str, Any]:
    visits = client.get("/api/doctor/visits").json()["visits"]
    (visit,) = [v for v in visits if v["reception_no"] == reception_no]
    return visit


def _d3_receptions(client: TestClient) -> list[str | None]:
    visits = client.get("/api/doctor/visits").json()["visits"]
    return [v["reception_no"] for v in visits]


def _count(client: TestClient, table: str) -> int:
    with db_conn(client.app) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _text_found_in_db(client: TestClient, needles: tuple[str, ...]) -> list[str]:
    """全ての表の全ての列を見て、needles のどれかを含む `表.列` を返す。"""
    found: list[str] = []
    with db_conn(client.app) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for table in (t["name"] for t in tables):
            for column in conn.execute(f"PRAGMA table_info({table})").fetchall():
                name = column["name"]
                rows = conn.execute(f'SELECT "{name}" AS v FROM {table}').fetchall()
                values = [r["v"] for r in rows if isinstance(r["v"], str)]
                if any(n in v for v in values for n in needles):
                    found.append(f"{table}.{name}")
    return found


def _assert_received_records_are_gone(client: TestClient) -> None:
    assert {t: _count(client, t) for t in ("entries", "closed_answers")} == {
        "entries": 0,
        "closed_answers": 0,
    }
    assert _count(client, "free_texts") == 0
    assert _text_found_in_db(client, SECRETS) == []
    assert _text_found_in_db_files(client, SECRETS) == []


def _text_found_in_db_files(client: TestClient, needles: tuple[str, ...]) -> list[str]:
    """DB のファイル（WAL も）のバイト列に残っている needles。消した行の跡も見る。"""
    path = Path(client.app.state.settings.db_path)
    raw = [f.read_bytes() for f in path.parent.glob(f"{path.name}*")]
    return [n for n in needles if any(n.encode("utf-8") in b for b in raw)]


def _assert_marks_stay(client: TestClient, pid: str) -> None:
    with db_conn(client.app) as conn:
        marks = db.list_record_marks(conn, pid)
    assert {m.record_date.isoformat() for m in marks} == MARKED_DAYS
    patients = client.get("/api/doctor/patients").json()["patients"]
    (row,) = [p for p in patients if p["id"] == pid]
    assert row["last_record_date"] == TODAY
    days = client.get(f"/api/patient/{pid}/visit-days").json()["visits"]
    assert [d["visit_date"] for d in days] == [TODAY]


# ---------------------------------------------------------------------------
# 受付 → D3 → 紙
# ---------------------------------------------------------------------------


def test_marks_and_records_reach_the_paper(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _patient_client(tmp_path) as client:
        pid = _new_patient(client)
        phone = _Phone(client, pid, monkeypatch)
        phone.record_course()
        # 受付の前は、印だけがある（中身はサーバーに無い）
        assert _count(client, "entries") == 0
        phone.send_visit()

        visit = _d3_row(client)
        assert visit["status"] == "ready"
        assert visit["fallback"] is False
        assert visit["patient_id"] == pid
        assert visit["unprocessed_count"] == 0
        total = client.get(f"/api/doctor/patients/{pid}/entries").json()["total"]
        assert total == 4  # 届いた日だけ。前コースの1件を含む

        r = client.get(f"/api/doctor/visits/{visit['id']}/report")
        assert r.status_code == 200, r.text
        html = r.text
        runner = client.app.state.runner_factory.runner
    assert runner.denied() == []
    (prompt,) = runner.prompts
    sent_to_claude = prompt_input(prompt)
    assert [e["day"] for e in sent_to_claude["entries"]] == [6, 7, 14]
    assert LOST_IN_C3 not in [e["record_date"] for e in sent_to_claude["entries"]]
    assert "届いていない" not in prompt

    # 今コース（C3）の Day に並ぶ。印だけの日は経過表では空白で、「入力なし」に数えない
    assert "第3コース　2026-10-27〜2026-11-09" in html
    diarrhea = grid_row(html, "c3-diarrhea")
    assert sorted(diarrhea) == list(range(1, 15))
    assert "hard" in diarrhea[6][0] and "○" in diarrhea[6][1]  # クローズ回答と AI の ○
    assert "too_sick" in diarrhea[7][0]
    assert "no_input" in diarrhea[10][0]
    temperature = grid_row(html, "c3-temperature")
    assert "37.2" in temperature[14][1]
    assert "no_input" in temperature[10][0]  # 届かなかった日の 37.2 は紙に出ない
    # 前コースの印は今コースの「届いていない」に入らない。前コースは閉じた回答だけ
    assert "記録が届いていない日: Day10" in html
    assert "Day10, " not in html
    assert "・届いていない1" in html
    assert "入力なし10" in html  # 14 日 − 記録 3 日 − 届いていない 1 日
    assert QUOTE in html and TODAY_NOTE in html
    assert PREVIOUS_COURSE_NOTE not in html


def test_printing_erases_the_received_records_everywhere(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _patient_client(tmp_path) as client:
        pid = _new_patient(client)
        phone = _Phone(client, pid, monkeypatch)
        phone.record_course()
        phone.send_visit()
        visit = _d3_row(client)
        assert _count(client, "entries") == 4
        assert _count(client, "free_texts") == 3
        assert _text_found_in_db(client, SECRETS) != []  # 受付から印刷までは置かれる
        assert _text_found_in_db_files(client, SECRETS) != []  # 検査が効いている

        r = client.post(f"/api/doctor/visits/{visit['id']}/printed")
        assert r.status_code == 200, r.text
        _assert_received_records_are_gone(client)
        _assert_marks_stay(client, pid)
        assert RECEPTION not in _d3_receptions(client)
        gone = client.get(f"/api/doctor/visits/{visit['id']}/report")
        assert gone.status_code != 200


def test_second_open_visit_keeps_the_records_until_it_is_printed(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """番号を間違えて受診が2つあるときは、最後の受診が閉じるまで消さない（D6 が原文を読む）。"""
    with _patient_client(tmp_path) as client:
        pid = _new_patient(client)
        phone = _Phone(client, pid, monkeypatch)
        phone.record_course()
        phone.send_visit("A-023")
        phone.send_visit("A-024")
        assert _count(client, "entries") == 4  # 同じ記録は二重にならない

        first, second = _d3_row(client, "A-023"), _d3_row(client, "A-024")
        assert client.post(f"/api/doctor/visits/{first['id']}/printed").is_success
        assert _count(client, "entries") == 4
        assert client.get(f"/api/doctor/visits/{second['id']}/report").is_success

        assert client.post(f"/api/doctor/visits/{second['id']}/printed").is_success
        _assert_received_records_are_gone(client)


# ---------------------------------------------------------------------------
# 24 時間の期限
# ---------------------------------------------------------------------------


def test_ttl_erases_the_received_records_at_24_hours(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _patient_client(tmp_path) as client:
        pid = _new_patient(client)
        phone = _Phone(client, pid, monkeypatch)
        phone.record_course()
        phone.send_visit()
        assert _d3_row(client)["status"] == "ready"
        with db_conn(client.app) as conn:
            just_before = now() + timedelta(hours=23, minutes=59)
            assert db.purge_expired(conn, just_before) == 0
        assert _count(client, "entries") == 4

        with db_conn(client.app) as conn:
            assert db.purge_expired(conn, now() + timedelta(hours=24, minutes=1)) == 1
        _assert_received_records_are_gone(client)
        _assert_marks_stay(client, pid)
        assert RECEPTION not in _d3_receptions(client)


def test_periodic_purge_erases_the_received_records_on_a_later_day(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """医師が開かなくても、周期の掃除（purge_once）が次の日に消す。時計だけを進める。"""
    with _patient_client(tmp_path) as client:
        pid = _new_patient(client)
        phone = _Phone(client, pid, monkeypatch)
        phone.record_course()
        phone.send_visit()
        monkeypatch.setenv("TSUTAE_TODAY", "2026-11-11")
        assert app_module.purge_once(client.app.state.settings) == 1
        _assert_received_records_are_gone(client)
        monkeypatch.setenv("TSUTAE_TODAY", TODAY)
        login_doctor(client)
        _assert_marks_stay(client, pid)


# ---------------------------------------------------------------------------
# 次の受診: 端末に残った前コースの記録をもう一度送る（§5.1）
# ---------------------------------------------------------------------------


def test_next_visit_receives_the_previous_course_again(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _patient_client(tmp_path) as client:
        pid = _new_patient(client)
        phone = _Phone(client, pid, monkeypatch)
        phone.record_course()
        phone.send_visit()
        visit = _d3_row(client)
        assert client.post(f"/api/doctor/visits/{visit['id']}/printed").is_success
        assert _count(client, "entries") == 0

        # 次のコース（C4）は 11/10 が Day1。Day3 に記録し、Day5 は印だけ、Day14 が受診日
        with db_conn(client.app) as conn:
            db.upsert_course(
                conn,
                Course(patient_id=pid, course_no=4, infusion_date=date(2026, 11, 10)),
            )
        diarrhea = {"question_key": "diarrhea", "value": "present", "temperature": None}
        fever = {"question_key": "fever", "value": "not_measured", "temperature": None}
        next_visit = "2026-11-23"
        phone.record("2026-11-12", answers=[diarrhea])
        lost = phone.record("2026-11-14", answers=[fever])
        phone.record(next_visit, answers=[fever], free_text=TODAY_NOTE + "2")
        monkeypatch.setenv("TSUTAE_TODAY", next_visit)
        login_doctor(client)

        window = client.get(f"/api/patient/{pid}/visit-window").json()
        assert window == {"start": "2026-10-27", "end": next_visit}
        body = phone.visit_body("B-101")
        body["entries"] = [
            e
            for e in body["entries"]
            if e is not lost and window["start"] <= e["record_date"] <= window["end"]
        ]
        r = client.post("/api/visit", json=body)
        assert r.status_code == 200, r.text

        visit = _d3_row(client, "B-101")
        assert visit["status"] == "ready"
        assert visit["fallback"] is False  # AI の変換が実際に通った
        runner = client.app.state.runner_factory.runner
        assert runner.denied() == []
        # Claude への入力は今コース（C4）の記録だけ。前コースは紙の閉じた回答にだけ使う
        days = [e["day"] for e in prompt_input(runner.prompts[-1])["entries"]]
        assert days == [3, 14]
        html = client.get(f"/api/doctor/visits/{visit['id']}/report").text
        assert _count(client, "entries") == len(body["entries"])

        # 今回は C4。前コースの C3 は端末から届いた閉じた回答で埋まる
        assert "第4コース" in html
        assert "hard" in grid_row(html, "c3-diarrhea")[6][0]
        assert "present" in grid_row(html, "c4-diarrhea")[3][0]
        # 届いていないのは今コースの Day5 だけ（C3 の Day10 は前コースなので数えない）
        assert "記録が届いていない日: Day5" in html
        assert "・届いていない1" in html
        assert QUOTE not in html  # 前コースの自由記載は紙に出さない


# ---------------------------------------------------------------------------
# Web Push の判定は同じ印を見る（どの端末で書いても、記録の中身が消えた後でも）
# ---------------------------------------------------------------------------


def _subscribe(client: TestClient, pid: str, endpoint: str) -> None:
    r = client.put(
        f"/api/patient/{pid}/push-subscription", json=subscription_body(endpoint)
    )
    assert r.status_code == 200, r.text


def _sent_to(sender: FakePushSender) -> list[str]:
    return [target.endpoint for target, _payload in sender.calls]


def _due(client: TestClient, sender: FakePushSender, at: datetime) -> PushCounts:
    return send_due_once(client.app.state.settings, sender, at)


def test_push_is_not_sent_to_the_patient_who_recorded_today(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = FakePushSender()
    with _patient_client(tmp_path, **vapid_overrides()) as client:
        wrote = _new_patient(client)
        phone = _Phone(client, wrote, monkeypatch)
        _subscribe(client, wrote, subscription_body()["endpoint"])
        entry = phone.record(TODAY, too_sick=True)  # つらい日も書いた扱い

        silent = _new_patient(client)
        _subscribe(client, silent, SECOND_ENDPOINT)

        assert _due(client, sender, EVENING) == PushCounts(sent=1)
        assert _sent_to(sender) == [SECOND_ENDPOINT]

        # 取り消して印が消えれば、まだ書いていない日になる
        assert register(client, wrote).status_code == 200
        undo = client.post(
            f"/api/patient/{wrote}/record-marks/undo",
            json={"recorded_at": entry["recorded_at"], "clear_mark": True},
        )
        assert undo.status_code == 200, undo.text
        later = EVENING + timedelta(minutes=1)
        assert _due(client, sender, later) == PushCounts(sent=1)
        assert _sent_to(sender) == [
            SECOND_ENDPOINT,
            subscription_body()["endpoint"],
        ]


def test_push_still_sees_the_mark_after_the_records_are_erased(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """記録の中身が印刷で消えても、印は残る。次の日は書いていないので送る。"""
    sender = FakePushSender()
    with _patient_client(tmp_path, **vapid_overrides()) as client:
        pid = _new_patient(client)
        phone = _Phone(client, pid, monkeypatch)
        _subscribe(client, pid, SECOND_ENDPOINT)
        phone.record_course()
        phone.send_visit()
        visit = _d3_row(client)
        assert client.post(f"/api/doctor/visits/{visit['id']}/printed").is_success
        assert _count(client, "entries") == 0

        assert _due(client, sender, EVENING) == PushCounts()
        assert sender.calls == []

        tomorrow = EVENING + timedelta(days=1)
        assert _due(client, sender, tomorrow) == PushCounts(sent=1)
        assert _sent_to(sender) == [SECOND_ENDPOINT]

"""dump_api_fixtures.py のスマホ保存の経路の台本（plan-device-records §5）。

記録の印 → 端末の記録を受付で送る → 範囲・受診日・取り消し・登録の解除・撮影の見本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api_helpers import db_conn, set_patient_cookie

from tsutae import db
from tsutae.schemas import EntryCreate


def record_mark_flow(
    rec: Any, demo: str, other: str, at: datetime, skill_version: str
) -> None:
    """受け取った記録は印刷で消えるので、医師の画面の fixture に今日の行が残るよう、
    client_entry_id の無い行も1件入れる（印刷でも消えない）。
    """
    mark = rec.call("patient_record_mark", "POST", f"/api/patient/{demo}/record-marks")
    answers = [
        {"question_key": "fever", "value": "measured", "temperature": 38.2},
        {"question_key": "diarrhea", "value": "present", "temperature": None},
    ]
    with db_conn(rec.client.app) as conn:
        db.add_entry(conn, demo, EntryCreate(answers=answers), at, skill_version)
    entry = {
        "client_entry_id": "11111111-1111-4111-8111-111111111111",
        "recorded_at": mark["recorded_at"],
        "record_date": mark["record_date"],
        "kind": "answers",
        "by_proxy": False,
        "skill_version": skill_version,
        "answers": answers,
        "free_text": None,
    }
    rec.call(
        "visit_with_entries",
        "POST",
        "/api/visit",
        {"reception_no": "A-023", "entries": [entry]},
    )
    bad = {**entry, "answers": [{"question_key": "unknown_question", "value": "none"}]}
    rec.call(
        "visit_entries_invalid",
        "POST",
        "/api/visit",
        {"reception_no": "A-023", "entries": [bad]},
        expect=422,
    )
    rec.call("patient_visit_window", "GET", f"/api/patient/{demo}/visit-window")
    rec.call("patient_visit_days", "GET", f"/api/patient/{demo}/visit-days")
    _undo_flow(rec, demo, other, mark["recorded_at"])


def _undo_flow(rec: Any, demo: str, other: str, recorded_at: str) -> None:
    """取り消し（§5.4）。受付の後は 409、受付の無い患者は印を消せる。登録の解除も同じ患者で。"""
    rec.call(
        "patient_record_mark_undo_not_undoable",
        "POST",
        f"/api/patient/{demo}/record-marks/undo",
        {"recorded_at": recorded_at, "clear_mark": True},
        expect=409,
    )
    with rec.without_cookies():
        set_patient_cookie(rec.client, other)
        marked = rec.client.post(f"/api/patient/{other}/record-marks")
        if marked.status_code != 200:
            raise RuntimeError(f"印: status {marked.status_code}")
        rec.call(
            "patient_record_mark_undo",
            "POST",
            f"/api/patient/{other}/record-marks/undo",
            {"recorded_at": marked.json()["recorded_at"], "clear_mark": True},
        )
        rec.client.post(f"/api/patient/{other}/record-marks")  # 応答が届かなかった1回目
        retried = rec.client.post(f"/api/patient/{other}/record-marks")
        if retried.status_code != 200:
            raise RuntimeError(f"印: status {retried.status_code}")
        rec.call(
            "patient_record_mark_undo_retried",
            "POST",
            f"/api/patient/{other}/record-marks/undo",
            {
                "recorded_at": retried.json()["recorded_at"],
                "clear_mark": True,
                "retried": True,
            },
        )
        rec.call(
            "patient_unregister",
            "POST",
            f"/api/patient/{other}/unregister",
            {"endpoint": None},
        )


def demo_tools_flow(rec: Any, demo: str, other: str) -> None:
    """撮影用の見本（§5.10）。デモ患者だけに出る。"""
    rec.call("patient_demo_config", "GET", f"/api/patient/{demo}/demo-config")
    rec.call("patient_demo_entries", "GET", f"/api/patient/{demo}/demo-entries")
    with rec.without_cookies():
        set_patient_cookie(rec.client, other)
        rec.call(
            "patient_demo_config_other",
            "GET",
            f"/api/patient/{other}/demo-config",
        )
        rec.call(
            "patient_demo_entries_other",
            "GET",
            f"/api/patient/{other}/demo-entries",
            expect=404,
        )

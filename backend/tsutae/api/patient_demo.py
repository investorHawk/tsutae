"""撮影用の見本（docs/plan-device-records.md §5.10）。`TSUTAE_DEMO_TOOLS=1` のときだけ動く。

- `GET /{pid}/demo-config`: この患者の設定に「見本の記録を入れる」を出してよいか（真偽だけ）
- `GET /{pid}/demo-entries`: デモ患者にだけ、合成データ（data/synthetic）の記録を端末の形（§5.1。
  質問の文の写しを含む）で返す。ID は `demo-<seq>` なので押し直しても増えない。今日より先の
  記録は返さない。環境変数が無いとき・デモ患者でないときは 404

環境変数が無ければ、経路は Cookie を見る前に 404 にして、有る無しも探れないようにする。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Request

from tsutae.api.deps import ApiError, AppSettings, Conn, require_patient
from tsutae.api.skill_questions import version_questions
from tsutae.config import SYNTHETIC_DIR, today
from tsutae.dataset import to_entries
from tsutae.schemas import Entry, SyntheticPatient
from tsutae.synthetic import load_patient

__all__ = ["router"]

router = APIRouter(prefix="/api/patient")

_DEMO_FILE = "demo_patient.json"


def _demo_patient() -> SyntheticPatient:
    return load_patient(SYNTHETIC_DIR / _DEMO_FILE)


def _question_texts(conn: sqlite3.Connection, skill_version: str) -> dict[str, str]:
    questions = version_questions(conn, skill_version) or []
    return {q.key: q.text for q in questions}


def _device_entry(pid: str, entry: Entry, texts: dict[str, str]) -> dict[str, Any]:
    """端末の記録の形（§5.1）。"""
    return {
        "pid": pid,
        "client_entry_id": f"demo-{entry.id}",
        "recorded_at": entry.recorded_at.isoformat(timespec="microseconds"),
        "record_date": entry.record_date.isoformat(),
        "kind": entry.kind,
        "by_proxy": entry.by_proxy,
        "skill_version": entry.skill_version,
        "answers": [
            {
                **answer.model_dump(mode="json"),
                "question_text": texts.get(answer.question_key),
            }
            for answer in entry.answers
        ],
        "free_text": entry.free_text,
    }


@router.get("/{pid}/demo-config")
def demo_config(
    pid: str, request: Request, conn: Conn, settings: AppSettings
) -> dict[str, bool]:
    patient = require_patient(pid, request, conn)
    enabled = settings.demo_tools and patient["id"] == _demo_patient().patient_id
    return {"demo_tools": enabled}


@router.get("/{pid}/demo-entries")
def demo_entries(
    pid: str, request: Request, conn: Conn, settings: AppSettings
) -> dict[str, Any]:
    if not settings.demo_tools:
        raise ApiError(404, "not_found")
    patient = require_patient(pid, request, conn)
    source = _demo_patient()
    if patient["id"] != source.patient_id:
        raise ApiError(404, "not_found")
    day = today()
    entries = [e for e in to_entries(source) if e.record_date <= day]
    texts = {
        version: _question_texts(conn, version)
        for version in {e.skill_version for e in entries}
    }
    return {
        "entries": [
            _device_entry(patient["id"], e, texts[e.skill_version]) for e in entries
        ]
    }

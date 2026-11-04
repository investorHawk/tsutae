"""dump_api_fixtures.py の D4 レジメンの台本（下書き・直接編集・確認・採用）。症例は全て合成。

`regimen_drafts_flow(rec)` を dump_api_fixtures の `_run` の最後に呼ぶ（rec は `Recorder`）。
新規の下書きを FOLFIRI＋BV（`backend/tests/regimen_fixtures.py`）にして採用し、既存の
CAPOX の版2の下書きの差分を見て捨てる（FOLFOX は先の台本が旧 D4 で版2にしていて
form が無い）。Claude の1往復（T94）はまだ無いので、AI の値（出どころ standard）は
DB に直接置く。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from api_helpers import db_conn
from regimen_fixtures import extra_form, fill_patch

from tsutae.db import repo_regimen_drafts as repo
from tsutae.regimen.form import load_form_json

__all__ = ["BASE", "regimen_drafts_flow"]

BASE = "/api/doctor/regimen-drafts"
STANDARD_FIELD = "basic.target"


def _patch_body(patch: Any) -> dict[str, Any]:
    return {
        "changes": [asdict(c) for c in patch.changes],
        "adds": [asdict(a) for a in patch.adds],
        "deletes": list(patch.deletes),
    }


def _mark_standard(rec: Any, draft_id: int) -> None:
    """Claude が標準の値として入れた欄の代わり（T94 の set_fields が書く出どころ）。"""
    with db_conn(rec.client.app) as conn:
        draft = repo.get_draft(conn, draft_id)
        repo.update_draft_form(
            conn,
            draft_id,
            form_json=draft["form_json"],
            sources_json=draft["sources_json"].replace(
                f'"{STANDARD_FIELD}":"doctor_edit"', f'"{STANDARD_FIELD}":"standard"'
            ),
            regimen=draft["regimen"],
        )


def _new_draft(rec: Any) -> int:
    draft = rec.call("doctor_regimen_draft_create", "POST", BASE, {"from": "new"})[
        "draft"
    ]
    draft_id = int(draft["id"])
    with db_conn(rec.client.app) as conn:
        form = load_form_json(repo.get_draft(conn, draft_id)["form_json"])
    body = _patch_body(fill_patch(form, extra_form("folfiri_bv")))
    rec.call("doctor_regimen_draft_fields", "PATCH", f"{BASE}/{draft_id}/fields", body)
    bad = {"changes": [{"field_id": "drugs.d-bv.name", "value": "ベバシズマブ 5mg/kg"}]}
    rec.call(
        "doctor_regimen_draft_fields_invalid",
        "PATCH",
        f"{BASE}/{draft_id}/fields",
        bad,
        expect=422,
    )
    return draft_id


def _adopt(rec: Any, draft_id: int) -> None:
    path = f"{BASE}/{draft_id}"
    _mark_standard(rec, draft_id)
    token = rec.call("doctor_regimen_draft_preview", "GET", f"{path}/preview")[
        "confirm_token"
    ]
    unconfirmed = {"confirm_token": token, "ai_values_confirmed": False}
    rec.call(
        "doctor_regimen_draft_adopt_unconfirmed",
        "POST",
        f"{path}/adopt",
        unconfirmed,
        expect=409,
    )
    old = {"confirm_token": "0" * 64, "ai_values_confirmed": True}
    rec.call(
        "doctor_regimen_draft_adopt_token_mismatch",
        "POST",
        f"{path}/adopt",
        old,
        expect=409,
    )
    body = {"confirm_token": token, "ai_values_confirmed": True}
    rec.call("doctor_regimen_draft_adopt", "POST", f"{path}/adopt", body)


def regimen_drafts_flow(rec: Any) -> None:
    """新規 → 直接編集 → 一覧 → 確認 → 採用、既存の版2の下書き → 差分 → 破棄。"""
    draft_id = _new_draft(rec)
    rec.call("doctor_regimen_drafts", "GET", BASE)
    rec.call("doctor_regimen_draft", "GET", f"{BASE}/{draft_id}")
    _adopt(rec, draft_id)
    existing = rec.call(
        "doctor_regimen_draft_create_existing",
        "POST",
        BASE,
        {"skill": "regimen-capox"},
    )["draft"]
    path = f"{BASE}/{existing['id']}"
    notes = {"changes": [{"field_id": "notes", "value": "施設の決まりを書く欄"}]}
    rec.call("doctor_regimen_draft_fields_existing", "PATCH", f"{path}/fields", notes)
    rec.call("doctor_regimen_draft_preview_diff", "GET", f"{path}/preview")
    rec.call("doctor_regimen_draft_discard", "POST", f"{path}/discard")
    rec.call(
        "doctor_regimen_draft_discard_closed",
        "POST",
        f"{path}/discard",
        expect=409,
    )
    rec.call("doctor_regimen_draft_missing", "GET", f"{BASE}/999", expect=404)

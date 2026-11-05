"""dump_api_fixtures.py の D4 レジメンの台本（下書き・直接編集・確認・採用）。症例は全て合成。

`regimen_drafts_flow(rec)` を dump_api_fixtures の `_run` の最後に呼ぶ（rec は `Recorder`）。
新規の下書きを FOLFIRI＋BV（`backend/tests/regimen_fixtures.py`）にして採用し、既存の
CAPOX の版2の下書きの差分を見て捨てる（FOLFOX は先の台本が旧 D4 で版2にしていて
form が無い）。採用の台本の AI の値（出どころ standard）は DB に直接置く。

Claude の1往復（T94。`POST .../turns`）は、別の新しい下書きで、偽の chat
（`backend/tests/regimen_chat_fakes.py` の ScriptChat・FailingChat）を
`app.state.regimen_chat` に置いて流す（成功・失敗の行・H1 の 422）。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from api_helpers import db_conn
from regimen_chat_fakes import FailingChat, ScriptChat, change
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
    # 採用した版の薬が候補に増えた形
    rec.call("doctor_regimen_drug_names", "GET", "/api/doctor/regimen-drug-names")


def _turn_chat() -> ScriptChat:
    ask = {
        "field": "drugs.1.days",
        "question": "ベバシズマブは何日目に点滴しますか",
        "options": ["Day1", "Day1・15"],
    }
    return ScriptChat(
        [
            change("basic.display_name", "FOLFIRI＋BV"),
            change("basic.cycle_days", 14),
            change("basic.target", "大腸がん", "standard"),
            (
                "set_fields",
                {
                    "add_rows": ["drugs.1"],
                    "changes": [
                        {
                            "field": "drugs.1.name",
                            "value": "ベバシズマブ",
                            "source": "doctor_text",
                        },
                        {
                            "field": "drugs.1.route",
                            "value": "infusion",
                            "source": "standard",
                        },
                    ],
                },
            ),
            # 先生が文で指定した質問（症状がそろう前の standard の提案は not_ready）
            (
                "propose_questions",
                {"from_library": ["diarrhea"], "source": "doctor_text"},
            ),
            ("ask", ask),
        ],
        reply="名前・1コースの日数・ベバシズマブを入れ、下痢の質問を足しました。"
        "点滴の日を選んでください",
    )


def _turns(rec: Any) -> None:
    """Claude の1往復: 成功（欄・ask・質問）→ 失敗（会話に失敗の行）→ H1 の 422。"""
    created = rec.client.post(BASE, json={"from": "new"})
    path = f"{BASE}/{created.json()['draft']['id']}/turns"
    state = rec.client.app.state
    saved = state.regimen_chat
    try:
        state.regimen_chat = _turn_chat()
        text = {
            "text": "FOLFIRI＋BV を作りたい。14日ごと、ベバシズマブも使う。"
            "下痢の質問も入れて"
        }
        rec.call("doctor_regimen_draft_turn", "POST", path, text)
        state.regimen_chat = FailingChat(RuntimeError("偽の失敗"))
        again = {"text": "点滴の日は Day1"}
        rec.call("doctor_regimen_draft_turn_failed", "POST", path, again)
        h1 = {"text": "受付 A-023 の方と同じにして"}
        rec.call("doctor_regimen_draft_turn_h1", "POST", path, h1, expect=422)
    finally:
        state.regimen_chat = saved


def regimen_drafts_flow(rec: Any) -> None:
    """新規 → 直接編集 → 一覧 → 確認 → 採用、既存の版2の下書き → 差分 → 破棄、往復。"""
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
    _turns(rec)
    rec.call("doctor_regimen_draft_missing", "GET", f"{BASE}/999", expect=404)

"""デモの筋書きを TestClient で通す結合テスト（docs/spec.md 3・6・9・10・11 節、docs/plan.md）。

筋書き: 合成3人を投入 → 医師がログインして患者一覧・コース → 患者が登録・質問集・記録
（38.0℃で固定規則、つらくて書けない、家族の代わり入力）→ 受付（A-023）→
台本どおりの FakeRunner（正解ラベルが AI の結果）で ready → 医師がレポートを読む →
D6（未処理の原文）・D5（Hook の発火、文面なし）→ 印刷済みで削除。別の筋として
runner の失敗・タイムアウト（AI変換なし）、D4（質問を足す → 承認 → 翌日の質問集と
経過表の「−−」）、24時間 TTL、生成の途中で印刷済み・期限切れになった受診を生き返らせない
こと、医師 API の認証（Cookie 無し・改ざん・失効）。Claude への入力は合成データから独立に
数えた期待値と JSON ごと比べる。API は呼ばない。症例は全て合成。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from api_helpers import db_conn, record_entry, register
from claude_agent_sdk import ClaudeSDKError
from e2e_scripts import (
    DEMO_PID,
    DEMO_RECEPTION,
    NEW_QUESTION_KEY,
    NEW_QUESTION_LABEL,
    NEW_QUESTION_TEXT,
    UNPROCESSED_SEQ,
    InterruptingRunner,
    adopt_new_question,
    bad_doctor_tokens,
    close_visit,
    demo_client,
    demo_runner,
    doctor_calls,
    doctor_cookie,
    doctor_login,
    expected_pipeline_input,
    find_visit,
    grid_row,
    post_visit,
    prompt_input,
    report_html,
    section,
    set_runner,
    skill_file,
)
from fastapi.testclient import TestClient
from pipeline_fakes import RaisingRunner, SlowRunner

from tsutae import db
from tsutae.api.fixed_rules import notices_for
from tsutae.pipeline.prompt import JSON_FENCE
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL
from tsutae.report.labels import has_severity_word
from tsutae.schemas import EntryCreate
from tsutae.skills import load_regimen_skill
from tsutae.synthetic import all_patients

FOLFOX_KEYS = ["numbness", "diarrhea", "stomatitis", "nausea_appetite", "fever"]
SYNTHETIC_IDS = {p.patient_id for p, _labels in all_patients()}
UNPROCESSED_TEXT = "磯鷲さんにもらった漢方をのんでみた。おなかがあったかい感じ"
PROXY_TEXT = "家族が代わりに入力。夕方は少しだけ食べられた"


def _answers(fever: float | None = None, **values: str) -> list[dict[str, Any]]:
    """FOLFOX の5問（既定は「なし」・熱は測っていない）。"""
    out: list[dict[str, Any]] = [
        {"question_key": k, "value": values.get(k, "none")} for k in FOLFOX_KEYS[:4]
    ]
    if fever is None:
        out.append({"question_key": "fever", "value": "not_measured"})
    else:
        out.append({"question_key": "fever", "value": "measured", "temperature": fever})
    extra = {k: v for k, v in values.items() if k not in FOLFOX_KEYS}
    out += [{"question_key": k, "value": v} for k, v in extra.items()]
    return out


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with demo_client(tmp_path) as c:
        yield c


# ---------------------------------------------------------------------------
# (1)(2) 投入と医師の患者一覧・コース
# ---------------------------------------------------------------------------


def test_doctor_sees_seeded_patients_and_courses(client: TestClient) -> None:
    assert client.get("/api/doctor/patients").status_code == 401
    assert client.post("/api/doctor/login", json={"password": "x"}).status_code == 401
    doctor_login(client)
    patients = client.get("/api/doctor/patients").json()["patients"]
    assert {p["id"] for p in patients} == SYNTHETIC_IDS
    demo = next(p for p in patients if p["id"] == DEMO_PID)
    assert demo["regimen"] == "FOLFOX"
    assert demo["register_url"] == f"http://testserver/register?pid={DEMO_PID}"
    r = client.get(f"/api/doctor/patients/{DEMO_PID}/courses")
    assert r.status_code == 200
    courses = r.json()["courses"]
    assert [
        (c["course_no"], c["infusion_date"], c["planned_date"]) for c in courses
    ] == [
        (1, "2026-09-27", "2026-09-27"),
        (2, "2026-10-13", "2026-10-11"),  # 延期2日
        (3, "2026-10-27", "2026-10-27"),
    ]
    assert find_visit(client, DEMO_RECEPTION) is None  # まだ受付は無い


# ---------------------------------------------------------------------------
# (3) 患者: 登録 → 質問集 → 記録 → 履歴
# ---------------------------------------------------------------------------


# デモの「今日」（Day14）の記録4件: 38.0℃・37.9℃・つらくて書けない・代わり入力
TODAY_BODIES: list[dict[str, Any]] = [
    {"answers": _answers(fever=38.0, numbness="present")},
    {"answers": _answers(fever=37.9)},
    {"too_sick": True},
    {
        "by_proxy": True,
        "answers": _answers(stomatitis="present"),
        "free_text": PROXY_TEXT,
    },
]


def record_today(client: TestClient) -> list[int]:
    """TODAY_BODIES をこの順に記録する。"""
    return [record_entry(client, DEMO_PID, body) for body in TODAY_BODIES]


def _patient_view(client: TestClient) -> dict[str, Any]:
    """患者画面が読む応答（受診日と質問集）そのもの。"""
    out: dict[str, Any] = {}
    for name in ("visit-days", "questions"):
        r = client.get(f"/api/patient/{DEMO_PID}/{name}")
        assert r.status_code == 200, r.text
        out[name] = r.json()
    return out


def test_patient_registers_records_and_gets_fixed_rules(client: TestClient) -> None:
    r = client.post("/api/patient/register", json={"pid": "P-ZZZZZZZZ"})
    assert r.status_code == 404 and r.json() == {"error": "unknown_patient"}
    assert register(client, DEMO_PID).json() == {"ok": True}
    r = client.get(f"/api/patient/{DEMO_PID}/questions")
    assert r.status_code == 200
    body = r.json()
    assert body["skill_version"] == "regimen-folfox@1"
    assert [q["key"] for q in body["questions"]] == FOLFOX_KEYS
    assert body["fixed_rules"] == [
        {
            "question_key": "fever",
            "threshold_celsius": 38.0,
            "patient_string_key": "fixed_rule.fever_38",
        }
    ]
    strings = client.get("/api/patient/strings").json()
    assert "38.0℃以上" in strings["fixed_rule.fever_38"]
    skill = load_regimen_skill("FOLFOX", client.app.state.settings.skills_dir)
    notices = [
        notices_for(EntryCreate.model_validate(body), skill) for body in TODAY_BODIES
    ]
    assert notices == [["fixed_rule.fever_38"], [], [], []]
    fever38, _fever379, too_sick, proxy = record_today(client)
    with db_conn(client.app) as conn:
        saved = {e.id: e for e in db.list_entries(conn, DEMO_PID)}
    assert len(saved) == 40 + 4
    assert saved[fever38].kind == "answers" and saved[too_sick].kind == "too_sick"
    assert saved[proxy].kind == "mixed" and saved[proxy].by_proxy is True
    assert saved[proxy].free_text == PROXY_TEXT
    assert str(saved[proxy].record_date) == "2026-11-09"


def _visit_demo(client: TestClient, reception_no: str = DEMO_RECEPTION) -> Any:
    runner = demo_runner(client, reception_no=reception_no)
    set_runner(client, runner)
    doctor_login(client)
    visit = post_visit(client, reception_no)
    return runner, visit


def _check_prompt(runner: Any, questions: list[dict[str, Any]]) -> None:
    """Claude への入力を、合成データから独立に数えた期待値と JSON ごと比べる。"""
    assert runner.calls == 1 and runner.denied() == []
    (prompt,) = runner.prompts
    assert DEMO_RECEPTION not in prompt and DEMO_PID not in prompt
    assert "磯鷲" not in prompt  # 二次検出に掛かった記録は送らない
    sent = prompt_input(prompt)
    expected = expected_pipeline_input(TODAY_BODIES, questions)
    assert (
        len(expected["entries"]) == 13 + 4
    )  # C3 Day1〜14 の14件 − 未処理1件 ＋ 今日4件
    assert sent["entries"] == expected["entries"]
    assert sent == expected
    instructions = prompt.split(JSON_FENCE, 1)[0]
    for e in expected["entries"]:  # 指示の文に記録の文面を写さない
        text = e["masked_free_text"]
        assert text is None or text not in instructions


def _check_header_and_words(html: str) -> None:
    header = section(html, "header")
    assert DEMO_RECEPTION in header and DEMO_PID in header  # 紙には出る
    assert "第3コース" in header and "2026-10-27" in header
    assert "症例は全て合成" in html
    assert "AI変換なし" not in html
    assert not has_severity_word(html)  # Grade・軽症・重症 等を出さない
    assert (
        "用語名はこのアプリの用語の一覧から AI が当てはめた候補で、医師が確定する。"
        in html
    )


def _check_attention(html: str) -> None:
    att = section(html, "attention")
    assert 'class="att-contradiction"' in att
    assert "夕方から下痢が3回あった" in att and "クローズ回答「なし」" in att
    assert "37.9℃" in att and "38.0℃" in att  # 37.5℃以上（今コース）
    assert 'class="att-too_sick"' in att and "前コースも同じ Day" in att
    assert "未処理の記載あり" in att and "1件" in att
    order = [att.index(f'class="att-{k}"') for k in ("contradiction", "fever")]
    assert order == sorted(order)


def _check_grid(html: str) -> None:
    diarrhea = grid_row(html, "c3-diarrhea")
    cls, body = diarrhea[5]  # C3 Day5: クローズ「なし」の上の ○（食い違い）
    assert "st-none" in cls and "○" in body
    temp = grid_row(html, "c3-temperature")
    assert "37.9" in temp[8][1] and "38.0" in temp[14][1]
    assert grid_row(html, "c2-diarrhea")  # 前コースの行（クローズのみ）
    assert all("○" not in b for _c, b in grid_row(html, "c2-diarrhea").values())
    assert "slash" in grid_row(html, "c3-numbness")[3][0]  # Day3 つらくて書けない
    assert 'class="proxy-mark">代</span>' in section(html, "grid")


def _ai_markers(runner: Any) -> tuple[set[str], set[str]]:
    """(AI の結果の用語, AI の結果・レポートにしか出ない語・キー)。"""
    payloads = {s.tool_name: dict(s.tool_input) for s in runner.steps}
    timeline, report = payloads[EMIT_TIMELINE_TOOL], payloads[EMIT_REPORT_TOOL]
    terms = {e["term"] for e in timeline["events"]}
    terms |= {row["term"] for row in report["per_symptom"]}
    keys = ("source_quote", "free_text_quote", "representative_quote", "term")
    keys += ("contradictions", "per_symptom", "confidence", "recalled", "events")
    keys += ("closed_answer", "timeline", "report", "fallback", "unprocessed")
    words = {f'"{k}"' for k in keys}
    words |= {"クローズ回答", "食い違い", "AI変換", "症状別", "医師が確定する"}
    words |= {"unknown_before_honorific", "Grade"}
    return terms, words


def _check_patient_view_unchanged(
    client: TestClient, before: dict[str, Any], runner: Any
) -> None:
    """生成の後も、患者画面の応答は生成の前と同じで、AI の結果を含まない。

    受付で増えるのは受診日（visits）の1件だけで、日付と受付の時刻しか持たない。
    """
    after = _patient_view(client)
    visits = after["visit-days"]["visits"]
    assert before["visit-days"]["visits"] == []
    assert [set(v) for v in visits] == [{"visit_date", "received_at"}]
    assert visits[0]["visit_date"] == "2026-11-09"
    assert after["questions"] == before["questions"]  # 生成で変わらない
    terms, words = _ai_markers(runner)
    plain = json.dumps(before, ensure_ascii=False)
    ai_only = {t for t in terms | words if t not in plain}
    assert {"末梢神経障害", '"source_quote"'} <= ai_only
    dumped = json.dumps(after, ensure_ascii=False)
    assert [t for t in sorted(ai_only) if t in dumped] == []


def test_visit_report_d6_d5_and_printed(client: TestClient) -> None:
    register(client, DEMO_PID)
    record_today(client)
    before = _patient_view(client)
    runner, visit = _visit_demo(client)
    assert visit["status"] == "ready" and visit["fallback"] is False
    assert visit["patient_id"] == DEMO_PID and visit["unprocessed_count"] == 1
    _check_prompt(runner, before["questions"]["questions"])
    _check_patient_view_unchanged(client, before, runner)
    received = _patient_view(client)
    html = report_html(client, visit["id"])
    _check_header_and_words(html)
    _check_attention(html)
    _check_grid(html)
    assert "症状別の時系列" in html and "下痢" in section(html, "per-symptom")
    _check_unprocessed(client, visit["id"])
    _check_events(client, visit["id"])
    _check_doctor_auth(client, visit["id"], html)
    _check_printed(client, visit["id"])
    # 印刷済みでも、受付で受け取っていない既存の記録と受診日は残る
    assert _patient_view(client) == received
    with db_conn(client.app) as conn:
        assert len(db.list_entries(conn, DEMO_PID)) == 40 + 4


def _check_doctor_auth(client: TestClient, visit_id: int, html: str) -> None:
    """医師 API は Cookie 無し・改ざん・別の鍵・失効のどれでも 401（患者 Cookie では通らない）。"""
    calls = doctor_calls(visit_id)
    for state, token in bad_doctor_tokens(client).items():
        with doctor_cookie(client, token):
            for method, path, body in calls:
                r = client.request(method, path, json=body)
                got = (r.status_code, r.json())
                assert got == (401, {"error": "not_logged_in"}), (state, method, path)
    # 401 の呼び出しは何も変えていない（印刷済みにも、患者・コース・Skill 変更の追加にもならない）
    assert report_html(client, visit_id) == html
    assert find_visit(client, DEMO_RECEPTION)["status"] == "ready"
    patients = client.get("/api/doctor/patients").json()["patients"]
    assert {p["id"] for p in patients} == SYNTHETIC_IDS
    courses = client.get(f"/api/doctor/patients/{DEMO_PID}/courses").json()
    assert [c["course_no"] for c in courses["courses"]] == [1, 2, 3]
    assert client.get("/api/doctor/skill-changes").json() == {"skill_changes": []}


def _check_unprocessed(client: TestClient, visit_id: int) -> None:
    r = client.get(f"/api/doctor/visits/{visit_id}/unprocessed")
    assert r.status_code == 200
    body = r.json()
    assert body["visit"]["reception_no"] == DEMO_RECEPTION
    assert body["visit"]["patient_id"] == DEMO_PID
    assert body["entries"] == [
        {
            "entry_id": UNPROCESSED_SEQ,
            "record_date": "2026-11-05",
            # 第3コース（Day1 = 2026-10-27）の Day10
            "course_no": 3,
            "day": 10,
            "reason": "unknown_before_honorific",
            "text": UNPROCESSED_TEXT,
            # 疑われた語「磯鷲さん」の原文の中の位置（D7-2）
            "marks": [{"start": 0, "end": 4}],
            "doctor_mask": None,  # 医師の伏せ字はまだ無い
        }
    ]
    assert "磯鷲" not in report_html(client, visit_id)  # 紙には載せない


def _check_events(client: TestClient, visit_id: int) -> None:
    r = client.get(f"/api/doctor/pipeline/{visit_id}/events")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    events = body["events"]
    hooks = {e["hook_name"] for e in events if e["hook_name"]}
    assert {"H1", "H2", "H4"} <= hooks
    names = {e["event"] for e in events}
    assert {"run_start", "run_end", "subagent_start", "visit_ready"} <= names
    agents = {e["agent_type"] for e in events if e["event"] == "subagent_start"}
    assert agents == {"date-normalizer", "contradiction-finder", "term-mapper"}
    # ts（時刻の数字）は除いて調べる（"37.9" が秒の値と偶然一致しないように）
    dumped = json.dumps(
        [{k: v for k, v in e.items() if k != "ts"} for e in events], ensure_ascii=False
    )
    for text in ("下痢", "磯鷲", "漢方", "37.9", DEMO_RECEPTION, DEMO_PID):
        assert text not in dumped, text  # 文面・識別子を出さない


def _check_printed(client: TestClient, visit_id: int, entries: int = 44) -> None:
    r = client.post(f"/api/doctor/visits/{visit_id}/printed")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/doctor/visits/{visit_id}/report").status_code == 404
    assert client.get(f"/api/doctor/visits/{visit_id}/unprocessed").status_code == 404
    assert find_visit(client, DEMO_RECEPTION) is None
    assert all(
        v["id"] != visit_id for v in client.get("/api/doctor/visits").json()["visits"]
    )
    with db_conn(client.app) as conn:
        saved = db.get_visit(conn, visit_id)
        assert saved["status"] == "printed" and saved["reception_no"] is None
        assert db.get_report(conn, visit_id) is None
        assert db.get_timeline(conn, visit_id) is None
        assert len(db.list_entries(conn, DEMO_PID)) == entries  # 生の記録は残す


# ---------------------------------------------------------------------------
# (9) runner の失敗 → AI変換なし
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "code"),
    [(ClaudeSDKError("boom"), "sdk_error"), (RuntimeError("boom"), "internal_error")],
)
def test_runner_failure_gives_fallback_report(
    client: TestClient, exc: BaseException, code: str
) -> None:
    register(client, DEMO_PID)
    set_runner(client, RaisingRunner(exc))
    doctor_login(client)
    visit = post_visit(client, DEMO_RECEPTION)
    assert visit["status"] == "ready" and visit["fallback"] is True
    html = report_html(client, visit["id"])
    assert "AI変換なし" in html and "症例は全て合成" in html
    assert DEMO_RECEPTION in section(html, "header")
    att = section(html, "attention")
    assert 'class="att-contradiction"' not in att  # 食い違いは調べていない
    assert "37.9℃" in att and "未処理の記載あり" in att
    diarrhea = grid_row(html, "c3-diarrhea")
    assert diarrhea and all("○" not in b for _c, b in diarrhea.values())
    assert "夕方から下痢が3回あった" in section(html, "quotes")  # 引用は同じ
    assert not has_severity_word(html)
    events = client.get(f"/api/doctor/pipeline/{visit['id']}/events").json()
    assert {"event": "fallback", "decision": code}.items() <= next(
        e for e in events["events"] if e["event"] == "fallback"
    ).items()
    r = client.get(f"/api/doctor/visits/{visit['id']}/unprocessed")
    assert [e["entry_id"] for e in r.json()["entries"]] == [UNPROCESSED_SEQ]


def _events(client: TestClient, visit_id: int) -> dict[str, Any]:
    r = client.get(f"/api/doctor/pipeline/{visit_id}/events")
    assert r.status_code == 200, r.text
    return r.json()


def _decisions(events: dict[str, Any], name: str) -> list[Any]:
    return [e["decision"] for e in events["events"] if e["event"] == name]


def test_runner_timeout_gives_printable_fallback(
    tmp_path: Path, fixed_today: str
) -> None:
    runner = SlowRunner(5.0)  # タイムアウト（0.05 秒）より十分長い
    with demo_client(tmp_path, pipeline_timeout_s=0.05) as client:
        register(client, DEMO_PID)
        set_runner(client, runner)
        doctor_login(client)
        visit = post_visit(client, DEMO_RECEPTION)
        assert runner.calls == 1 and runner.cancelled is True  # 打ち切られた
        assert visit["status"] == "ready" and visit["fallback"] is True
        events = _events(client, visit["id"])
        assert _decisions(events, "fallback") == ["timeout"]
        assert _decisions(events, "run_end") == ["timeout"]
        assert _decisions(events, "visit_ready") == ["fallback"]
        html = report_html(client, visit["id"])
        assert "AI変換なし" in html and DEMO_RECEPTION in section(html, "header")
        assert "37.9℃" in section(html, "attention")
        assert "夕方から下痢が3回あった" in section(html, "quotes")
        _check_printed(client, visit["id"], entries=40)  # AI変換なしでも消せる


# ---------------------------------------------------------------------------
# (9b) 生成の途中で印刷済み・期限切れ → 生成の終わりで生き返らせない
# ---------------------------------------------------------------------------


def _check_closed(client: TestClient, visit_id: int, how: str) -> None:
    with db_conn(client.app) as conn:
        saved = db.get_visit(conn, visit_id)
        assert saved["reception_no"] is None
        # 印刷済みは printed のまま。期限切れは状態を変えない（生成中のまま）
        assert saved["status"] == ("printed" if how == "printed" else "generating")
        assert db.get_report(conn, visit_id) is None
        assert db.get_timeline(conn, visit_id) is None
        names = [log["event"] for log in db.list_pipeline_logs(conn, "visit", visit_id)]
    assert "visit_closed" in names
    assert "visit_ready" not in names and "visit_failed" not in names
    assert find_visit(client, DEMO_RECEPTION) is None
    for tail in ("report", "unprocessed"):
        r = client.get(f"/api/doctor/visits/{visit_id}/{tail}")
        assert (r.status_code, r.json()) == (404, {"error": "not_found"}), tail
    assert _events(client, visit_id)["status"] == saved["status"]


@pytest.mark.parametrize("how", ["printed", "expired"])
@pytest.mark.parametrize("inner_kind", ["ai", "sdk_error"])
def test_visit_closed_during_generation_is_not_revived(
    client: TestClient, how: str, inner_kind: str
) -> None:
    register(client, DEMO_PID)
    inner: Any = (
        demo_runner(client)
        if inner_kind == "ai"
        else RaisingRunner(ClaudeSDKError("boom"))
    )
    runner = InterruptingRunner(inner, close_visit(client, how))
    set_runner(client, runner)
    doctor_login(client)
    r = client.post("/api/visit", json={"reception_no": DEMO_RECEPTION})
    assert r.status_code == 200, r.text
    assert runner.calls == 1 and inner.calls == 1
    if inner_kind == "ai":  # AI の結果まで出揃ってから保存しようとした
        allowed = [o.tool_name for o in inner.outcomes if o.decision == "allow"]
        assert {EMIT_TIMELINE_TOOL, EMIT_REPORT_TOOL} <= set(allowed)
    with db_conn(client.app) as conn:
        (visit,) = db.list_visits(conn)
    _check_closed(client, visit["id"], how)


# ---------------------------------------------------------------------------
# (10) D4 レジメン: 質問を1つ足す → 確認（差分）→ 採用 → 版 2 → 翌日の質問集と経過表の「−−」
#      （v1.1。旧 D4 の一文の書き換えは report-format だけ。regimen-* は use_regimen_editor）
# ---------------------------------------------------------------------------


@pytest.fixture
def d4_client(tmp_path: Path, fixed_today: str):
    with demo_client(tmp_path) as c:
        yield c


def _approve_new_question(client: TestClient) -> None:
    doctor_login(client)
    before = skill_file(client).read_text("utf-8")
    r = client.post(
        "/api/doctor/skill-changes",
        json={
            "skill_name": "regimen-folfox",
            "request_text": "口内炎は、食事がとれたかも次から聞いて",
        },
    )
    assert r.status_code == 400 and r.json() == {"error": "use_regimen_editor"}
    assert skill_file(client).read_text("utf-8") == before
    preview = adopt_new_question(client)
    assert f"+  - {{key: {NEW_QUESTION_KEY}" in preview["skill_md"]["text"]
    assert preview["adopted"]["version"] == 2
    skills = {
        s["name"]: s["version"]
        for s in client.get("/api/doctor/skills").json()["skills"]
    }
    assert skills["regimen-folfox"] == 2
    skill = load_regimen_skill("FOLFOX", client.app.state.settings.skills_dir)
    assert skill.version == 2 and NEW_QUESTION_KEY in [q.key for q in skill.questions]


def _next_day_entry(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-10")
    body = client.get(f"/api/patient/{DEMO_PID}/questions").json()
    assert body["skill_version"] == "regimen-folfox@2"
    texts = {q["key"]: q["text"] for q in body["questions"]}
    assert texts[NEW_QUESTION_KEY] == NEW_QUESTION_TEXT
    answers = _answers(stomatitis="present", **{NEW_QUESTION_KEY: "present"})
    record_entry(client, DEMO_PID, {"answers": answers})
    with db_conn(client.app) as conn:
        older, latest = db.list_entries(conn, DEMO_PID)[-2:]
    assert latest.skill_version == "regimen-folfox@2"
    assert NEW_QUESTION_KEY in [a.question_key for a in latest.answers]
    assert older.skill_version == "regimen-folfox@1"


def test_skill_change_updates_next_day_questions_and_grid(
    d4_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = d4_client
    register(client, DEMO_PID)
    before = client.get(f"/api/patient/{DEMO_PID}/questions").json()
    assert before["skill_version"] == "regimen-folfox@1"
    _approve_new_question(client)
    _next_day_entry(client, monkeypatch)
    _runner, visit = _visit_demo(
        client, reception_no="A-031"
    )  # 医師の Cookie も取り直す
    assert visit["status"] == "ready" and visit["fallback"] is False
    html = report_html(client, visit["id"])
    grid = section(html, "grid")  # 未知の key は版の form の短い名前が行名（v1.1）
    assert f">{NEW_QUESTION_LABEL}<" in grid and NEW_QUESTION_TEXT not in grid
    row = grid_row(html, f"c3-{NEW_QUESTION_KEY}")
    for day in (12, 13):  # 前の日（v1 の記録がある日）は未設問
        cls, body = row[day]
        assert "st-not_asked" in cls and "−−" in body, (day, cls)
    assert "st-present" in row[15][0]  # 翌日（Day15）の回答
    earlier = {cls for d, (cls, _b) in row.items() if d <= 14}
    assert not any(
        s in c for c in earlier for s in ("st-present", "st-none", "st-hard")
    )
    assert "st-none" in grid_row(html, "c3-diarrhea")[13][0]  # 既存の行はそのまま


# ---------------------------------------------------------------------------
# (11) 24時間 TTL
# ---------------------------------------------------------------------------


def test_report_expires_after_24_hours(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client, DEMO_PID)
    _runner, visit = _visit_demo(client)
    assert visit["status"] == "ready"
    assert report_html(client, visit["id"])
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-11")  # 受付から24時間より後
    doctor_login(client)
    assert find_visit(client, DEMO_RECEPTION) is None
    assert client.get(f"/api/doctor/visits/{visit['id']}/report").status_code == 404
    with db_conn(client.app) as conn:
        saved = db.get_visit(conn, visit["id"])
        assert saved["reception_no"] is None
        assert db.get_report(conn, visit["id"]) is None
        assert db.get_timeline(conn, visit["id"]) is None
        assert len(db.list_entries(conn, DEMO_PID)) == 40  # 生の記録は残す

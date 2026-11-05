"""T97 の紙の通し: 28日・質問7問・前コースありの RAM＋wPTX の紙が読めるか（API を呼ばない）。

test_regimen_ram_wptx_flow.py（採用 → 1記録 → 紙の短い名前）と
test_regimen_mixed_versions_flow.py（版の混ざる受診）に重ならないよう、紙の読みやすさの形
（列・行・ヘッダ・前コース・紙に出ない文・エスケープ）を見る。

- 採用は D4 の画面と同じ HTTP API（下書き → PATCH → 確認 → 採用。Claude を呼ばない直接編集）
- 医師 API で患者を登録し、第1コース（2026-09-15〜10-12、28日）と第2コース（10-13〜。
  今日 2026-11-09 が Day28）を持たせる。患者 API で両コースに記録する（日付を進めて）
- 受診のレポートを、偽の AI 変換（FakeRunner の台本）と、AI 変換なし（台本なし → フォール
  バック）の両方で作る
- 経過表は 1 段 21 列まで（grid_view.GRID_MAX_COLS）なので、28日は Day1〜21 と Day22〜28 の
  2 段に折り返す。どちらの段にも前コースの行が出る
- 紙に Claude の自由文が入らないことは2つの経路で見る: 変換の emit に余分な自由文の欄を
  足すと拒否されて紙に出ない（schemas の extra="forbid"。受け付けた正しい emit だけが紙に
  出る）。D4 のチャットの Claude の返答・問いの文は、採用した SKILL.md にも紙にも出ない
- 環境変数 TSUTAE_PAPER_OUT に置き場所を入れると、紙の HTML をそこに書き出す
  （docs/eval/d4-regimen-paper/ の画像を作り直すとき）
"""

from __future__ import annotations

import html as html_lib
import os
import re
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import api_client, login_doctor, record_entry, register
from e2e_scripts import grid_row, live_prepared, post_visit, report_html, section
from fastapi.testclient import TestClient
from pipeline_fakes import FakeRunner, Step, standard_steps
from regimen_chat_fakes import ScriptChat
from regimen_fixtures import fill_patch, ram_wptx_data

from tsutae.config import SKILLS_HOME
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL
from tsutae.regimen import RegimenForm

NAME = "regimen-ram-wptx"
DRAFTS = "/api/doctor/regimen-drafts"
RECEPTION = "C-201"
TODAY = "2026-11-09"
C1_INFUSION = "2026-09-15"  # 第1コース Day1（Day28 = 2026-10-12）
C2_INFUSION = "2026-10-13"  # 第2コース Day1（今日 2026-11-09 が Day28）
DAYS = list(range(1, 29))

# 経過表の行（Skill の質問の順。体温の質問は体温行 `temperature` に畳む）と短い名前
ROWS: list[tuple[str, str]] = [
    ("neuropathy", "しびれ"),  # SHORT_LABELS に無い key。form の label から
    ("diarrhea", "下痢"),
    ("stomatitis", "口内炎"),
    ("nausea_appetite", "吐き気・食欲"),
    ("fatigue", "だるさ"),
    ("bleeding", "出血"),
    ("temperature", "体温"),
]

# 記録（日付 → 記録の本文の部品）。第1コースは前コース（クローズ回答だけが紙に出る）
C1_RECORDS: dict[str, dict[str, Any]] = {
    "2026-09-15": {"present": ["diarrhea"], "free_text": "少しお腹がゆるい"},
    "2026-09-19": {"hard": ["nausea_appetite"]},
    "2026-09-26": {"too_sick": True},  # Day12
    "2026-10-04": {"present": ["neuropathy"], "temperature": 37.2},
    "2026-10-12": {},  # Day28
}
C2_RECORDS: dict[str, dict[str, Any]] = {
    "2026-10-15": {"present": ["fatigue"], "free_text": "今日はだるい"},  # Day3
    "2026-10-21": {  # Day9
        "present": ["bleeding", "neuropathy"],
        "free_text": "鼻血が出た。手足のしびれもある",
    },
    "2026-10-28": {"too_sick": True},  # Day16
    "2026-11-03": {"temperature": 38.1},  # Day22
    TODAY: {"present": ["fatigue"]},  # Day28
}
# 偽の AI 変換の出来事: (記録日, Day, 用語, 版の term_keys でつながる質問 key, 引用)
AI_EVENTS: list[tuple[str, int, str, str, str]] = [
    ("2026-10-15", 3, "倦怠感", "fatigue", "今日はだるい"),
    ("2026-10-21", 9, "鼻出血", "bleeding", "鼻血が出た"),
    ("2026-10-21", 9, "末梢性感覚ニューロパチー", "neuropathy", "手足のしびれ"),
]

# 紙に出てはいけない SKILL.md の文（補足の指示・本文の見出し・質問文）
SKILL_ONLY_TEXTS = (
    "手足のむくみは用語の一覧に無い",
    "記録を時系列に直すための指示",
    "だるさや疲れやすさはありましたか",
    "鼻血や歯ぐきからの出血はありましたか",
    "手足のしびれはありましたか",
)

# SKILL.md の本文と紙のテンプレートの両方に、決まった文として出る行（漏れではない）
SHARED_FIXED_TEXTS = frozenset({"症例は全て合成（架空）"})
MIN_SKILL_LINE = 6  # これより短い行（「## 1.」の見出し番号など）は見ない

_COL_HEAD = re.compile(r'<th class="col-head[^"]*" data-day="(\d+)">')
_SEGMENT = re.compile(
    r'<div class="grid-segment" data-segment="(\d+)" data-days="([^"]+)">'
)
_ROW_LABEL = re.compile(
    r'<tr><th class="row-label">([^<]*)</th><td [^>]*data-row="([^"]+)"'
)


# ---------------------------------------------------------------------------
# 準備: 採用（D4 の HTTP API）・患者・記録
# ---------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


@pytest.fixture
def client(tmp_path: Path, home: Path, fixed_today: str) -> Iterator[TestClient]:
    with api_client(tmp_path, skills_dir=home / ".claude" / "skills") as c:
        login_doctor(c)
        yield c


def _patch_body(base: RegimenForm, target: RegimenForm) -> dict[str, Any]:
    patch = fill_patch(base, target)
    return {
        "changes": [{"field_id": c.field_id, "value": c.value} for c in patch.changes],
        "adds": [{"section": a.section, "row_id": a.row_id} for a in patch.adds],
        "deletes": list(patch.deletes),
    }


def _new_draft(client: TestClient) -> dict[str, Any]:
    r = client.post(DRAFTS, json={"from": "new"})
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def _fill_and_adopt(
    client: TestClient, draft: dict[str, Any], data: dict[str, Any]
) -> None:
    """下書きのフォームを data の値にし（直接編集の PATCH）、確認 → 採用する。"""
    base = RegimenForm.model_validate(draft["form"])  # 画面が受け取るフォームの値
    body = _patch_body(base, RegimenForm.model_validate(data))
    path = f"{DRAFTS}/{draft['id']}"
    r = client.patch(f"{path}/fields", json=body)
    assert r.status_code == 200, r.text
    r = client.get(f"{path}/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["issues"] == [], preview["issues"]
    r = client.post(
        f"{path}/adopt",
        json={"confirm_token": preview["confirm_token"], "ai_values_confirmed": True},
    )
    assert r.status_code == 200, r.text


def _adopt(client: TestClient, data: dict[str, Any]) -> None:
    _fill_and_adopt(client, _new_draft(client), data)


def _answers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, _label in ROWS[:-1]:
        value = "none"
        if key in spec.get("present", []):
            value = "present"
        if key in spec.get("hard", []):
            value = "hard"
        out.append({"question_key": key, "value": value})
    temp = spec.get("temperature")
    if temp is None:
        out.append({"question_key": "fever", "value": "not_measured"})
    else:
        out.append({"question_key": "fever", "value": "measured", "temperature": temp})
    return out


def _entry_body(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("too_sick"):
        return {"too_sick": True}
    body: dict[str, Any] = {"answers": _answers(spec)}
    if spec.get("free_text"):
        body["free_text"] = spec["free_text"]
    return body


def _patient_with_records(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    r = client.post("/api/doctor/patients", json={"regimen": "RAM-WPTX"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    for no, infusion in ((1, C1_INFUSION), (2, C2_INFUSION)):
        r = client.post(
            "/api/doctor/courses",
            json={"patient_id": pid, "course_no": no, "infusion_date": infusion},
        )
        assert r.status_code == 200, r.text
    assert register(client, pid).status_code == 200
    for day, spec in {**C1_RECORDS, **C2_RECORDS}.items():
        monkeypatch.setenv("TSUTAE_TODAY", day)
        body = client.get(f"/api/patient/{pid}/questions").json()
        assert body["skill_version"] == f"{NAME}@1"
        record_entry(client, pid, _entry_body(spec))
    monkeypatch.setenv("TSUTAE_TODAY", TODAY)
    login_doctor(client)  # 日付を動かしたので医師の Cookie を取り直す
    return pid


def _ai_payloads(client: TestClient, pid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """偽の AI 変換の emit_timeline / emit_report の入力（AI_EVENTS から）。"""
    prepared = live_prepared(client, pid, RECEPTION)
    by_date = {e.record_date.isoformat(): e for e in prepared.input.entries}
    events = [
        {
            "entry_no": by_date[d].entry_no,
            "date": d,
            "day": day,
            "course_no": 2,
            "term": term,
            "question_key": key,
            "status": "present",
            "source_quote": quote,
            "confidence": 0.9,
            "recalled": False,
            "by_proxy": False,
        }
        for d, day, term, key, quote in AI_EVENTS
    ]
    per_symptom = [
        {
            "term": term,
            "question_key": key,
            "start_day": day,
            "start_date": d,
            "representative_quote": quote,
            "confidence": 0.9,
        }
        for d, day, term, key, quote in AI_EVENTS
    ]
    return {"events": events, "contradictions": []}, {"per_symptom": per_symptom}


def _ai_steps(client: TestClient, pid: str) -> list[Step]:
    timeline, report = _ai_payloads(client, pid)
    return standard_steps(timeline, report, NAME)


StepsFor = Callable[[TestClient, str], list[Step]]


def _paper(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    steps_for: StepsFor | None,
    name: str,
) -> tuple[dict[str, Any], str, FakeRunner]:
    """患者・記録を作り、受診のレポートを作る。steps_for が None なら台本なし（フォールバック）。"""
    pid = _patient_with_records(client, monkeypatch)
    runner = FakeRunner(steps_for(client, pid) if steps_for else ())
    client.app.state.runner_factory.runner = runner
    visit = post_visit(client, RECEPTION)
    assert all(o.decision == "allow" for o in runner.outcomes), runner.outcomes
    html = report_html(client, visit["id"])
    _maybe_dump(html, name)
    return visit, html, runner


def _maybe_dump(html: str, name: str) -> None:
    out = os.environ.get("TSUTAE_PAPER_OUT")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / f"{name}.html").write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# 紙の形の検査（AI 変換あり・なしで共通）
# ---------------------------------------------------------------------------


def _assert_paper_shape(html: str) -> None:
    grid = section(html, "grid")
    assert _SEGMENT.findall(grid) == [("1", "1-21"), ("2", "22-28")]
    assert sorted(int(d) for d in _COL_HEAD.findall(grid)) == DAYS
    assert "（1/2）Day1〜Day21" in grid and "（2/2）Day22〜Day28" in grid
    assert 'class="grid dense"' in grid  # 1 列が 8mm の段は文字を詰める
    # どちらの段にも 今コース → 前コース の順で両方のブロックが出る（Day28 が今日）
    assert grid.count('<tbody class="current">') == 2
    assert grid.count('<tbody class="previous">') == 2
    assert grid.count("第2コース（今回）") == 2
    assert grid.count("第1コース（前コース。クローズ回答のみ）") == 2
    # 行: 各コース 7 行（しびれ〜体温）が段ごとに同じ順で出る
    expected = [(label, f"c{no}-{key}") for no in (2, 1) for key, label in ROWS] * 2
    assert _ROW_LABEL.findall(grid) == expected
    for no in (1, 2):
        for key, _label in ROWS:
            assert sorted(grid_row(html, f"c{no}-{key}")) == DAYS, (no, key)


def _assert_closed_answers(html: str) -> None:
    """クローズ回答は前コースにもそのまま出る（つらい・斜線・体温の値）。"""
    nausea = grid_row(html, "c1-nausea_appetite")
    assert "st-hard" in nausea[5][0]
    assert "slash" in grid_row(html, "c1-diarrhea")[12][0]  # Day12 つらくて書けない
    assert "37.2" in grid_row(html, "c1-temperature")[20][1]
    assert "st-no_input" in grid_row(html, "c1-diarrhea")[2][0]
    assert "st-present" in grid_row(html, "c2-bleeding")[9][0]
    assert "38.1" in grid_row(html, "c2-temperature")[22][1]
    assert "slash" in grid_row(html, "c2-fatigue")[16][0]  # Day16 つらくて書けない


def _marks(html: str, no: int) -> set[tuple[str, int]]:
    return {
        (key, day)
        for key, _label in ROWS
        for day, (_cls, body) in grid_row(html, f"c{no}-{key}").items()
        if "○" in body
    }


def _assert_no_skill_text(html: str, client: TestClient) -> None:
    text = html_lib.unescape(html)
    for phrase in SKILL_ONLY_TEXTS:
        assert phrase not in text, phrase
    skill_md = (client.app.state.settings.skills_dir / NAME / "SKILL.md").read_text(
        "utf-8"
    )
    body = skill_md.split("\n---\n", 1)[1]
    lines = {line.strip("-# *").strip() for line in body.splitlines()}
    checked = {
        line
        for line in lines
        if len(line) >= MIN_SKILL_LINE and line not in SHARED_FIXED_TEXTS
    }
    assert len(checked) >= 10  # 本文の行を拾えている
    leaked = sorted(line for line in checked if line in text)
    assert leaked == []


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------


def test_ai_paper_reads_28_days_7_rows_and_previous_course(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _adopt(client, ram_wptx_data())
    visit, html, _runner = _paper(
        client, monkeypatch, steps_for=_ai_steps, name="ram_wptx_ai"
    )
    assert visit["status"] == "ready" and visit["fallback"] is False, visit

    header = section(html, "header")
    assert "<td>RAM＋wPTX</td>" in header
    assert "第2コース　2026-10-13〜2026-11-09" in header
    _assert_paper_shape(html)
    _assert_closed_answers(html)
    # 自由記載の出来事は版の term_keys で足した質問の行につながる（今コースだけ）
    assert _marks(html, 2) == {("fatigue", 3), ("bleeding", 9), ("neuropathy", 9)}
    assert _marks(html, 1) == set()  # 前コースはクローズ回答だけ
    per_symptom = section(html, "per-symptom")
    assert "倦怠感" in per_symptom and "鼻出血" in per_symptom
    _assert_no_skill_text(html, client)


def test_fallback_paper_keeps_same_grid(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _adopt(client, ram_wptx_data())
    visit, html, _runner = _paper(
        client, monkeypatch, steps_for=None, name="ram_wptx_fallback"
    )
    assert visit["status"] == "ready" and visit["fallback"] is True, visit

    assert 'class="fallback-notice"' in html
    assert "<td>RAM＋wPTX</td>" in section(html, "header")
    _assert_paper_shape(html)
    _assert_closed_answers(html)
    assert _marks(html, 1) == _marks(html, 2) == set()
    assert "AI変換なしのため、この欄は空。" in section(html, "per-symptom")
    quotes = section(html, "quotes")
    assert "今日はだるい" in quotes and "鼻血が出た。手足のしびれもある" in quotes
    _assert_no_skill_text(html, client)


def test_display_name_and_label_are_escaped_on_paper(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = ram_wptx_data()
    data["basic"]["display_name"] = "RAM<i>&wPTX"
    data["questions"] = [
        {**q, "label": "だるさ<b>&"} if q["key"] == "fatigue" else q
        for q in data["questions"]
    ]
    _adopt(client, data)
    _visit, html, _runner = _paper(
        client, monkeypatch, steps_for=_ai_steps, name="ram_wptx_escape"
    )

    assert "<td>RAM&lt;i&gt;&amp;wPTX</td>" in section(html, "header")
    assert ">だるさ&lt;b&gt;&amp;<" in section(html, "grid")
    assert "<i>" not in html and "<b>" not in html
    assert "&wPTX" not in html.replace("&amp;wPTX", "")


# Claude の自由文（紙に出てはいけない。どれも SKILL.md・合成の記録に無い文）
FREE_SUMMARY = "総じて経過は良好で減量は不要と考えます"
FREE_NOTE = "この患者は抗がん剤を中止すべきです"
FREE_COMMENT = "主治医への申し送り：次回は採血を追加"
CHAT_REPLY = "RAM＋wPTX の欄を埋めました。ほかに足す質問はありますか"
CHAT_ASK = "しびれの質問を足しますか"


def _steps_with_free_text(client: TestClient, pid: str) -> list[Step]:
    """余分な自由文の欄を足した emit（拒否される）の後に、正しい emit を渡す台本。"""
    timeline, report = _ai_payloads(client, pid)
    bad_events = [{**timeline["events"][0], "note": FREE_NOTE}, *timeline["events"][1:]]
    bad_rows = report["per_symptom"]
    return [
        *standard_steps(timeline, report, NAME)[:-2],
        Step(EMIT_TIMELINE_TOOL, {**timeline, "summary": FREE_SUMMARY}),
        Step(EMIT_TIMELINE_TOOL, {**timeline, "events": bad_events}),
        Step(EMIT_TIMELINE_TOOL, timeline),
        Step(
            EMIT_REPORT_TOOL,
            {"per_symptom": [{**bad_rows[0], "comment": FREE_COMMENT}, *bad_rows[1:]]},
        ),
        Step(EMIT_REPORT_TOOL, report),
    ]


def test_free_text_in_emit_is_rejected_and_not_on_paper(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _adopt(client, ram_wptx_data())
    visit, html, runner = _paper(
        client, monkeypatch, steps_for=_steps_with_free_text, name="ram_wptx_free"
    )
    emits = [
        o
        for o in runner.outcomes
        if o.tool_name in (EMIT_TIMELINE_TOOL, EMIT_REPORT_TOOL)
    ]
    assert [bool((o.result or {}).get("is_error")) for o in emits] == [
        True,  # timeline の上に summary（extra="forbid"）
        True,  # 出来事に note
        False,
        True,  # 症状別の行に comment
        False,
    ]
    assert visit["status"] == "ready" and visit["fallback"] is False, visit
    assert _marks(html, 2) == {("fatigue", 3), ("bleeding", 9), ("neuropathy", 9)}
    text = html_lib.unescape(html)
    for phrase in (FREE_SUMMARY, FREE_NOTE, FREE_COMMENT):
        assert phrase not in text, phrase


def test_d4_chat_reply_is_not_in_skill_or_paper(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = {
        "field": "basic.display_name",
        "question": CHAT_ASK,
        "options": ["足す", "足さない"],
    }
    client.app.state.regimen_chat = ScriptChat([("ask", question)], reply=CHAT_REPLY)
    draft = _new_draft(client)
    r = client.post(
        f"{DRAFTS}/{draft['id']}/turns", json={"text": "RAM＋wPTX。1コースは28日"}
    )
    assert r.status_code == 200 and r.json()["turn_error"] is None, r.text
    draft = r.json()["draft"]
    # 返答と問いの文は下書きの会話（院内の画面）には出る
    said = repr(draft["chat"])
    assert CHAT_REPLY in said and CHAT_ASK in said
    _fill_and_adopt(client, draft, ram_wptx_data())
    skill_md = (client.app.state.settings.skills_dir / NAME / "SKILL.md").read_text(
        "utf-8"
    )
    _visit, html, _runner = _paper(
        client, monkeypatch, steps_for=_ai_steps, name="ram_wptx_chat"
    )
    text = html_lib.unescape(html)
    for phrase in (CHAT_REPLY, CHAT_ASK):
        assert phrase not in skill_md, phrase
        assert phrase not in text, phrase

"""scripts/run_demo_regimen.py（D4 レジメンをチャットで作る通しの先生用のスクリプト）。

API は呼ばない。Claude の代わりに往復ごとに違う手順を返す偽の chat（`SequenceChat`。
中身は regimen_chat_fakes の ScriptChat）か、SdkRegimenChat＋偽の query（ToolQuery）を
差し込む。本体の backend/skills_home は実行の前後で1バイトも変わらないことを確かめる。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from regimen_chat_fakes import FailingChat, ScriptChat, ToolQuery, result_message
from regimen_fixtures import folfiri_bv_data

from tsutae.config import REPO_ROOT, SKILLS_HOME, Settings
from tsutae.masking import detect_identifiers
from tsutae.regimen.chat_sdk import SdkRegimenChat
from tsutae.regimen.chat_types import TurnInput, TurnResult

SCRIPT = REPO_ROOT / "scripts" / "run_demo_regimen.py"
DISPLAY = "FOLFIRI＋BV"
ASK = (
    "ask",
    {
        "field": "basic.display_name",
        "question": "画面に出す名前はどうしますか",
        "options": [DISPLAY, "FOLFIRI-BV"],
    },
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_demo_regimen", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass が自分のモジュールを引くため
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """.env を読ませない（先生の環境でもキーなしを試せるように）。"""
    module = _load()
    monkeypatch.setattr(module, "load_env_file", lambda *a, **k: False)
    monkeypatch.delenv("TSUTAE_DB", raising=False)
    monkeypatch.delenv("TSUTAE_SKILLS_DIR", raising=False)
    return module


def _snapshot() -> dict[str, tuple[bytes, int]]:
    return {
        str(p.relative_to(SKILLS_HOME)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(SKILLS_HOME.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# 偽の Claude の手順（FOLFIRI＋BV。plan §5）
# ---------------------------------------------------------------------------


def _set(ref: str, value: Any, source: str = "doctor_text") -> dict[str, Any]:
    return {"field": ref, "value": value, "source": source}


def fill_calls() -> list[tuple[str, dict[str, Any]]]:
    """1往復目: 表示名以外の基本・薬・注意する症状を入れ、表示名を聞く。"""
    data = folfiri_bv_data()
    basic = data["basic"]
    changes = [
        _set("basic.code", basic["code"]),
        _set("basic.target", basic["target"]),
        _set("basic.cycle_days", basic["cycle_days"]),
    ]
    add_rows = []
    for i, drug in enumerate(data["drugs"], start=1):
        add_rows.append(f"drugs.{i}")
        changes += [
            _set(f"drugs.{i}.name", drug["name"]),
            _set(f"drugs.{i}.route", drug["route"]),
            _set(f"drugs.{i}.days", drug["days"]),
        ]
    effects = [e for e in data["side_effects"] if e["question_key"] != "fever"]
    for i, effect in enumerate(effects, start=1):
        add_rows.append(f"side_effects.{i}")
        changes += [
            _set(f"side_effects.{i}.phrases", effect["phrases"], "standard"),
            _set(f"side_effects.{i}.ctcae_terms", effect["ctcae_terms"], "standard"),
        ]
    set_fields = {"add_rows": add_rows, "changes": changes}
    return [("set_fields", set_fields), ASK]


def answer_calls() -> list[tuple[str, dict[str, Any]]]:
    return [("set_fields", {"changes": [_set("basic.display_name", DISPLAY)]})]


def propose_calls() -> list[tuple[str, dict[str, Any]]]:
    return [
        (
            "propose_questions",
            {
                "from_library": ["diarrhea", "nausea_appetite", "stomatitis"],
                "new_questions": [
                    {
                        "key": "fatigue",
                        "label": "だるさ",
                        "text": "だるさや疲れやすさはありましたか",
                    }
                ],
            },
        )
    ]


@dataclass
class SequenceChat:
    """往復ごとに次の ScriptChat を使う偽の chat（尽きたら何もしない往復）。"""

    turns: list[ScriptChat]
    seen: list[str] = field(default_factory=list)

    async def turn(self, draft: TurnInput, text: str) -> TurnResult:
        self.seen.append(text)
        index = len(self.seen) - 1
        chat = self.turns[index] if index < len(self.turns) else ScriptChat([])
        return await chat.turn(draft, text)


def full_chat() -> SequenceChat:
    return SequenceChat(
        [
            ScriptChat(fill_calls(), reply="薬と症状を入れました。名前を聞きます"),
            ScriptChat(answer_calls(), reply="名前を入れました"),
            ScriptChat(propose_calls(), reply="質問を4つ足しました"),
        ]
    )


def _factory(chat: Any) -> Any:
    def make(settings: Settings) -> Any:
        return chat

    return make


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------


def test_canned_texts_pass_h1(script: ModuleType) -> None:
    """決まった文が H1 に掛かると先生の smoke が1往復目で止まる。"""
    texts = [script.DEFAULT_TEXT, script.PROPOSE_TEXT, script.FILL_TEXT]
    texts += [script.answer_text(o) for o in (DISPLAY, "FOLFIRI-BV", "はい")]
    for text in texts:
        assert detect_identifiers(text) == [], text


def test_without_key_exits_2(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = script.main(["--json", "--out-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "ANTHROPIC_API_KEY" in captured.err
    assert list(tmp_path.iterdir()) == []


def test_full_flow_answers_ask_and_proposes(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chat = full_chat()
    code = script.main(["--out-dir", str(tmp_path)], chat_factory=_factory(chat))
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert chat.seen == [
        script.DEFAULT_TEXT,
        script.answer_text(DISPLAY),
        script.PROPOSE_TEXT,
    ]
    out = captured.out
    assert "| 1 | 依頼 |" in out
    assert "| 2 | 答え |" in out
    assert "| 3 | 質問の提案 |" in out
    assert "未入力: 0" in out
    assert "採用: しない（--adopt を付けると一時の写しの上で採用する）" in out
    assert list(tmp_path.iterdir()) == []  # --json が無ければ書かない


def test_json_has_turns_and_totals(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(
        ["--json", "--out-dir", str(tmp_path)], chat_factory=_factory(full_chat())
    )
    out = capsys.readouterr().out
    assert code == 0, out
    files = sorted(tmp_path.glob("demo-regimen-*.json"))
    assert len(files) == 1 and str(files[0]) in out
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["status"] == "ok"
    assert data["limits"]["regimen_max_turns"] == 12
    assert data["limits"]["regimen_max_budget_usd"] == 1.0
    turns = data["turns"]
    assert [t["kind"] for t in turns] == ["request", "answer", "propose"]
    first = turns[0]
    assert first["cost_usd"] == 0.04 and first["tokens_in"] == 40
    assert first["ask"]["field_id"] == "basic.display_name"
    assert first["tool_calls"] == 2 and first["tool_rejected"] == 0
    assert first["h4_denied"] == 0 and first["turn_error"] is None
    assert first["changed"] > 10
    assert turns[1]["ask"] is None and turns[1]["missing"] == 0
    assert turns[2]["proposed"] == [
        "diarrhea",
        "nausea_appetite",
        "stomatitis",
        "fatigue",
    ]
    assert data["totals"]["turns"] == 3
    assert data["totals"]["asks"] == 1
    assert data["totals"]["cost_usd"] == pytest.approx(0.12)
    assert data["preview"]["issues"] == []
    assert data["preview"]["skill_name"] == "regimen-folfiri-bv"
    assert data["preview"]["ai_values"] > 0
    # 表と確認の数は同じ意味（標準の値の欄）。先生の文からの欄は sources にだけ残る
    standard = [k for k, v in data["sources"].items() if v == "standard"]
    assert turns[-1]["ai_fields"] == data["preview"]["ai_values"] == len(standard)
    assert "doctor_text" in data["sources"].values()
    assert data["adopt"] is None
    md = sorted(tmp_path.glob("demo-regimen-*.md"))
    assert len(md) == 1 and md[0].stem == files[0].stem
    assert (
        md[0].read_text(encoding="utf-8").startswith("---\nname: regimen-folfiri-bv\n")
    )


def test_adopt_on_copy_shows_choice_and_keeps_originals(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot()
    assert before
    code = script.main(
        ["--adopt", "--out-dir", str(tmp_path)], chat_factory=_factory(full_chat())
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "採用: regimen-folfiri-bv 版 1" in out
    assert "患者の登録の選択肢: FOLFIRI-BV（FOLFIRI＋BV）がある" in out
    assert _snapshot() == before
    assert not (SKILLS_HOME / ".claude" / "skills" / "regimen-folfiri-bv").exists()


def _file_state(path: Path) -> tuple[bytes, int] | None:
    return (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None


def test_adopt_uses_temporary_db_and_keeps_data_db(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """アプリに渡す設定の DB と Skill は一時ディレクトリの中で、data/ の DB は変わらない。"""
    real_db = script.get_settings().db_path
    assert real_db == REPO_ROOT / "data" / "tsutae.db"
    before = _file_state(real_db)
    seen: list[Settings] = []
    real_create_app = script.create_app

    def capture(settings: Settings, **kwargs: Any) -> Any:
        seen.append(settings)
        assert settings.db_path.parent.name.startswith("tsutae-demo-regimen-")
        return real_create_app(settings, **kwargs)

    monkeypatch.setattr(script, "create_app", capture)
    code = script.main(
        ["--adopt", "--out-dir", str(tmp_path)], chat_factory=_factory(full_chat())
    )
    assert code == 0, capsys.readouterr().out
    assert len(seen) == 1
    used = seen[0]
    tmp = used.db_path.parent
    assert used.db_path != real_db
    assert used.skills_dir.is_relative_to(tmp)
    assert not used.skills_dir.is_relative_to(SKILLS_HOME)
    assert not tmp.exists()  # 一時ディレクトリは終わったら消える
    assert _file_state(real_db) == before


def test_stops_at_max_turns_with_missing_fields(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Claude が何も入れなければ、上限の往復で止まり、採用せずに 1。"""
    chat = SequenceChat([])
    code = script.main(
        ["--adopt", "--json", "--max-turns", "2", "--out-dir", str(tmp_path)],
        chat_factory=_factory(chat),
    )
    out = capsys.readouterr().out
    assert code == 1
    assert len(chat.seen) == 2
    assert "採用: しない（確認の検査に掛かった）" in out
    data = json.loads(next(tmp_path.glob("demo-regimen-*.json")).read_text("utf-8"))
    assert data["status"] == "incomplete"
    assert data["preview"]["issues"]
    assert data["adopt"] is None


def test_turn_error_stops_and_still_writes_json(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """往復の失敗（ここでは chat の例外）で止め、JSON は書く。"""
    code = script.main(
        ["--json", "--out-dir", str(tmp_path)],
        chat_factory=_factory(FailingChat(RuntimeError("boom"))),
    )
    out = capsys.readouterr().out
    assert code == 1
    data = json.loads(next(tmp_path.glob("demo-regimen-*.json")).read_text("utf-8"))
    assert data["status"] == "failed"
    assert [t["turn_error"] for t in data["turns"]] == ["internal_error"]
    assert "internal_error" in out
    assert "boom" not in out


def test_sdk_chat_counts_hook_denials_and_cost(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SdkRegimenChat の組み立てごと（Hook・ResultMessage の費用）を偽の query で通す。"""
    queries = [
        ToolQuery([("Bash", {"command": "ls"}), *fill_calls()]),
        ToolQuery(answer_calls()),
        ToolQuery(propose_calls(), result_message("質問を足しました")),
    ]

    seen: list[str] = []

    def query_fn(*, prompt: str, options: Any) -> Any:
        query = queries[min(len(seen), len(queries) - 1)]
        seen.append(prompt)
        return query(prompt=prompt, options=options)

    def make(settings: Settings) -> Any:
        return SdkRegimenChat(settings, query_fn=query_fn)

    code = script.main(["--json", "--out-dir", str(tmp_path)], chat_factory=make)
    out = capsys.readouterr().out
    assert code == 0, out
    data = json.loads(next(tmp_path.glob("demo-regimen-*.json")).read_text("utf-8"))
    first = data["turns"][0]
    assert first["h4_denied"] == 1
    assert first["cost_usd"] == 0.05 and first["sdk_turns"] == 3
    assert data["totals"]["h4_denied"] == 1
    assert data["totals"]["cost_usd"] == pytest.approx(0.15)


def test_rejected_tool_call_is_counted(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """薬の量を入れようとした呼び出しは拒否され、拒否の数に入る。"""
    bad = ("set_fields", {"changes": [_set("drugs.9.name", "イリノテカン 150mg/m2")]})
    chat = SequenceChat(
        [
            ScriptChat([bad, *fill_calls()]),
            ScriptChat(answer_calls()),
            ScriptChat(propose_calls()),
        ]
    )
    code = script.main(
        ["--json", "--out-dir", str(tmp_path)], chat_factory=_factory(chat)
    )
    assert code == 0, capsys.readouterr().out
    data = json.loads(next(tmp_path.glob("demo-regimen-*.json")).read_text("utf-8"))
    assert data["turns"][0]["tool_rejected"] == 1
    assert data["totals"]["tool_rejected"] == 1


def test_propose_is_asked_once_even_if_nothing_is_added(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """提案の往復で何も足されなくても、同じ文を繰り返さずに止める。"""
    chat = SequenceChat([ScriptChat(fill_calls()), ScriptChat(answer_calls())])
    code = script.main(["--out-dir", str(tmp_path)], chat_factory=_factory(chat))
    out = capsys.readouterr().out
    assert code == 0, out
    assert chat.seen == [
        script.DEFAULT_TEXT,
        script.answer_text(DISPLAY),
        script.PROPOSE_TEXT,
    ]

"""scripts/run_demo_visit.py（デモ患者の受診を1回生成して確かめる先生用のスクリプト）。

API は呼ばない（--dry-run と、キーなしの終了だけを試す）。症例は全て合成。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from tsutae.config import REPO_ROOT, SYNTHETIC_DIR
from tsutae.synthetic import load_patient

SCRIPT = REPO_ROOT / "scripts" / "run_demo_visit.py"
DEMO = load_patient(SYNTHETIC_DIR / "demo_patient.json")
UNPROCESSED_SEQ = 38  # 二次検出に掛かる記載（辞書にない架空の姓＋さん）


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_demo_visit", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """.env を読ませない（先生の環境でもキーなしを試せるように）。"""
    module = _load()
    monkeypatch.setattr(module, "load_env_file", lambda *a, **k: False)
    monkeypatch.delenv("TSUTAE_TODAY", raising=False)
    monkeypatch.delenv("TSUTAE_DB", raising=False)
    return module


def _raw_texts() -> list[str]:
    return [e.free_text for e in DEMO.entries if e.free_text]


def _unprocessed_text() -> str:
    found = [e.free_text for e in DEMO.entries if e.seq == UNPROCESSED_SEQ]
    assert found and found[0]
    return found[0]


def test_dry_run_is_ready_and_writes_files(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "out"
    code = script.main(["--dry-run", "--out-dir", str(out_dir)])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "状態: ready" in captured.out
    assert "fallback: なし" in captured.out
    htmls = sorted(out_dir.glob("demo-visit-*.html"))
    jsons = sorted(out_dir.glob("demo-visit-*.json"))
    assert len(htmls) == 1 and len(jsons) == 1
    assert htmls[0].stem == jsons[0].stem
    assert htmls[0].stem.startswith("demo-visit-20261109-")
    assert str(htmls[0]) in captured.out and str(jsons[0]) in captured.out
    html = htmls[0].read_text(encoding="utf-8")
    assert DEMO.reception_no in html
    data = json.loads(jsons[0].read_text(encoding="utf-8"))
    timeline, report = data["timeline"], data["report_data"]
    assert timeline["events"] and timeline["contradictions"]
    assert len(timeline["unprocessed_entries"]) >= 1
    assert report["header"]["reception_no"] == DEMO.reception_no
    assert report["fallback"] is False
    assert f"events: {len(timeline['events'])}" in captured.out
    assert f"per_symptom: {len(report['per_symptom'])}" in captured.out


def test_dry_run_fires_hooks(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "H1: allow 1 / deny 0" in out
    assert "H2: allow 2 / deny 0" in out
    assert "H4: allow 7 / deny 0" in out


def test_output_has_no_identifier_or_raw_text(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    printed = captured.out + captured.err
    assert DEMO.reception_no in printed  # 受付番号は出してよい
    assert DEMO.patient_id not in printed
    for text in _raw_texts():
        assert text not in printed
    hidden = _unprocessed_text()
    for path in tmp_path.iterdir():
        assert hidden not in path.read_text(encoding="utf-8")


def test_without_key_exits_2(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = script.main(["--out-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "ANTHROPIC_API_KEY" in captured.err
    assert "--dry-run" in captured.err
    assert list(tmp_path.iterdir()) == []


def test_keeps_given_today(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """TSUTAE_TODAY があればそれを使う（受診日もその日になる）。"""
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-08")
    assert script.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "受診日: 2026-11-08" in out
    assert list(tmp_path.glob("demo-visit-20261108-*.html"))


def test_fallback_shows_error_code(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """偽物が何も出さなければ AI 変換なし（ready・fallback）で、理由のコードを出す。"""
    monkeypatch.setattr(
        script, "dry_run_runner", lambda *a, **k: script.DryRunRunner([])
    )
    assert script.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "状態: ready" in out
    assert "fallback: あり" in out
    assert "error_code: no_timeline" in out
    assert "events: 0" in out

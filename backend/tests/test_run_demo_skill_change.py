"""scripts/run_demo_skill_change.py（D4 の書き換えを1回だけ試す先生用のスクリプト）。

API は呼ばない（--dry-run と、キーなしの終了だけを試す）。本体の SKILL.md は
実行の前後で1バイトも変わらないことを確かめる。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from tsutae.config import REPO_ROOT, SKILLS_HOME

SCRIPT = REPO_ROOT / "scripts" / "run_demo_skill_change.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_demo_skill_change", SCRIPT)
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
    monkeypatch.delenv("TSUTAE_DB", raising=False)
    monkeypatch.delenv("TSUTAE_SKILLS_DIR", raising=False)
    return module


def _snapshot() -> dict[str, tuple[bytes, int]]:
    return {
        str(p.relative_to(SKILLS_HOME)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(SKILLS_HOME.rglob("*"))
        if p.is_file()
    }


def test_dry_run_is_pending_and_writes_files(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "out"
    code = script.main(["--dry-run", "--out-dir", str(out_dir)])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "状態: pending" in captured.out
    assert "error_code: -" in captured.out
    assert "差分: 追加 1 行 / 削除 0 行" in captured.out
    diffs = sorted(out_dir.glob("demo-skill-change-*.diff"))
    mds = sorted(out_dir.glob("demo-skill-change-*.md"))
    assert len(diffs) == 1 and len(mds) == 1
    assert diffs[0].stem == mds[0].stem
    assert str(diffs[0]) in captured.out and str(mds[0]) in captured.out
    diff = diffs[0].read_text(encoding="utf-8")
    assert diff.startswith("---")
    assert f"+  - {{key: {script.DRY_RUN_KEY}" in diff
    md = mds[0].read_text(encoding="utf-8")
    assert md.startswith("---\nname: regimen-folfox\n")
    assert "version: 1\n" in md  # 版は承認の時に上がる
    assert script.DRY_RUN_KEY in md and script.DRY_RUN_TEXT in md


def test_dry_run_counts_hooks_and_stats(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "H1: allow 1 / retry 0 / deny 0" in out
    assert "skill_check: allow 1 / retry 0 / deny 0" in out
    assert "H3: allow 0 / retry 0 / deny 0" in out
    assert "H4: allow 0 / retry 0 / deny 0" in out
    assert "トークン: 入力 0 / 出力 0  費用: 0.0 USD" in out
    assert "所要時間:" in out


def test_approve_makes_version_2_with_new_question(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(["--dry-run", "--approve", "--out-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "承認: regimen-folfox の版 2" in captured.out
    assert f"{script.DRY_RUN_KEY}: {script.DRY_RUN_TEXT}" in captured.out
    assert "stomatitis: 口の中の痛みや口内炎はありましたか" in captured.out
    lines = captured.out.splitlines()
    keys = [line.split(":")[0].strip() for line in lines if line.startswith("  ")]
    assert keys.index(script.DRY_RUN_KEY) == keys.index("stomatitis") + 1


def test_original_skills_untouched(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot()
    assert before  # 本体の SKILL.md がある
    assert script.main(["--dry-run", "--approve", "--out-dir", str(tmp_path)]) == 0
    assert "版 2" in capsys.readouterr().out
    assert _snapshot() == before


def test_custom_skill_and_request(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--skill で別の Skill を選べる（偽の editor は stomatitis の無い Skill を変えない）。"""
    code = script.main(
        [
            "--dry-run",
            "--skill",
            "report-format-default",
            "--request",
            "見出しを短くして",
            "--out-dir",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "状態: failed" in out
    assert "error_code: no_change" in out
    assert list(tmp_path.iterdir()) == []


def test_unknown_skill_exits_1(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = script.main(
        ["--dry-run", "--skill", "regimen-nothing", "--out-dir", str(tmp_path)]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "error_code: unknown_skill" in out


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

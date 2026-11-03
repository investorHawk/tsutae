"""tsutae.report.sample（正解ラベルを AI の出力の代わりにする）と scripts/render_sample_report.py。"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

from tsutae.config import REPO_ROOT
from tsutae.masking import detect_identifiers
from tsutae.report.sample import load_demo_inputs

SCRIPT = REPO_ROOT / "scripts" / "render_sample_report.py"


def test_prepared_covers_current_course_and_masks() -> None:
    sample = load_demo_inputs()
    prepared = sample.prepared
    assert prepared.input.schedule.course_no == 3
    dates = [e.record_date for e in prepared.input.entries]
    assert min(dates) >= date(2026, 10, 27) and max(dates) <= date(2026, 11, 9)
    assert [e.entry_no for e in prepared.input.entries] == list(
        range(1, len(prepared.input.entries) + 1)
    )
    # 二次検出に掛かる記録（seq 38）は外れ、未処理になる
    assert [u.entry_id for u in prepared.unprocessed] == [38]
    assert 38 not in prepared.entry_ids.values()
    for text in prepared.masked_texts.values():
        assert detect_identifiers(text) == []


def test_result_quotes_match_masked_texts() -> None:
    sample = load_demo_inputs()
    timeline = sample.result.timeline
    assert timeline is not None and timeline.events
    texts = sample.prepared.masked_texts
    for event in timeline.events:
        assert event.source_quote in texts[event.entry_no]
    for c in timeline.contradictions:
        assert c.free_text_quote in texts[c.entry_no]
    assert sample.result.picks is not None
    for s in sample.result.picks.per_symptom:
        assert any(s.representative_quote in t for t in texts.values())


def test_fallback_sample() -> None:
    sample = load_demo_inputs(fallback=True)
    assert sample.result.timeline is None and sample.result.fallback is True


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_script_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    proc = _run("--out", str(out))
    assert proc.returncode == 0, proc.stderr
    html = out.read_text(encoding="utf-8")
    assert "A-023" in html and "症例は全て合成" in html
    assert "AI変換なし" not in html
    assert str(out) in proc.stdout


def test_script_fallback(tmp_path: Path) -> None:
    out = tmp_path / "fallback.html"
    proc = _run("--fallback", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert "AI変換なし" in out.read_text(encoding="utf-8")

"""デモ患者 C3（受診日 2026-11-09、受付番号 A-023）のレポートを HTML に描く（目で確かめる用）。

正解ラベル（data/synthetic/labels_demo_patient.json）を AI の出力の代わりにする。
API を呼ばない。症例は全て合成。

    .venv/bin/python scripts/render_sample_report.py [--out PATH] [--fallback]

--out の既定は $TMPDIR/tsutae_sample_report.html。--fallback で「AI変換なし」版。
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from tsutae.report import build_report_data, render_report_html
from tsutae.report.sample import load_demo_inputs

DEFAULT_NAME = "tsutae_sample_report.html"


def _default_out() -> Path:
    return Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / DEFAULT_NAME


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None, help="書き出す HTML")
    parser.add_argument(
        "--fallback", action="store_true", help="AI変換なし（フォールバック）版を描く"
    )
    return parser.parse_args(argv)


def render_sample(*, fallback: bool) -> str:
    sample = load_demo_inputs(fallback=fallback)
    data = build_report_data(**sample.build_kwargs())
    skill = sample.report_skill
    return render_report_html(
        data,
        questions=list(sample.regimen_skill.questions),
        low_confidence_threshold=skill.low_confidence_threshold,
        sections=list(skill.sections),
        quotes_max_items=skill.quotes_max_items,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    out: Path = args.out or _default_out()
    html = render_sample(fallback=args.fallback)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    except OSError as exc:
        print(f"書き出せない: {out}（{exc.strerror}）", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

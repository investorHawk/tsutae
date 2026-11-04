"""デモ患者 P-DEMO0001 の受診（受付番号 A-023）を本物の Claude で1回だけ生成して確かめる。

実行（先生が Claude Code のプロンプトで。サンドボックス外）:
    ! .venv/bin/python scripts/run_demo_visit.py [--dry-run] [--out-dir DIR]

- DB は一時ディレクトリに作る（本番の DB に触れない）。デモ患者だけを入れ、今の SKILL.md を
  skill_versions に登録し、受診を作って `generate_visit_report` を1回 await する
- 「今日」は `TSUTAE_TODAY`（無ければ 2026-11-09）。受診日もその日
- 実行時間の上限は settings.pipeline_timeout_s（convert の中で掛かる）
- 終わったら状態・fallback・error_code・所要時間・トークン・費用・Hook の発火数・timeline と
  per_symptom の件数を出し、レポート HTML と timeline・ReportData の JSON を
  `<out-dir>/demo-visit-<YYYYMMDD-HHMM>.html|.json` に書く（既定の out-dir は docs/eval）
- 標準出力には件数・コードだけを出す（仮名ID・記録の文面は出さない）
- `--dry-run`: Claude の代わりに正解ラベル（labels_demo_patient.json）を返す偽物で同じ流れを
  通す（API を呼ばない。Hook は偽物が実際に呼ぶ）
- ANTHROPIC_API_KEY が無く --dry-run でもなければ終了コード 2。ready なら 0、それ以外は 1
- 症例は全て合成
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from tsutae import db
from tsutae.config import (
    REPO_ROOT,
    SYNTHETIC_DIR,
    Settings,
    get_settings,
    has_api_key,
    load_env_file,
    now,
    today,
)
from tsutae.course import current_course
from tsutae.dataset import to_courses, to_entries
from tsutae.pipeline.agents import AGENT_NAMES
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.runner import AgentRunner, SdkRunner
from tsutae.pipeline.service import ensure_skill_versions, generate_visit_report
from tsutae.pipeline.tools import (
    EMIT_REPORT_TOOL,
    EMIT_TIMELINE_TOOL,
    RunCollector,
    handle_emit_report,
    handle_emit_timeline,
)
from tsutae.report.sample import result_from_labels
from tsutae.schemas import ConversionResult, PreparedInput, RunStats, SyntheticPatient
from tsutae.skills import REGIMEN_SKILL_NAMES, load_regimen_skill, load_report_skill
from tsutae.synthetic import load_labels, load_patient

DEMO_CASE = "demo_patient"
DEFAULT_TODAY = "2026-11-09"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "eval"
HOOK_NAMES = ("H1", "H2", "H3", "H4")
NO_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY がありません。.env に書くか環境変数で渡してください。"
    "API を呼ばずに流れだけ確かめるなら --dry-run を付けてください。"
)


# ---------------------------------------------------------------------------
# 偽の runner（--dry-run。API は呼ばない）
# ---------------------------------------------------------------------------


def _matches(matcher: str | None, tool_name: str) -> bool:
    if matcher in (None, "", "*"):
        return True
    return re.fullmatch(f"(?:{matcher})", tool_name) is not None


def _hooks(options: ClaudeAgentOptions, event: str, tool_name: str = "") -> list:
    matchers = (options.hooks or {}).get(event, [])  # type: ignore[call-overload]
    return [h for m in matchers if _matches(m.matcher, tool_name) for h in m.hooks]


def _is_denied(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    out = result.get("hookSpecificOutput") or {}
    return out.get("permissionDecision") == "deny" or result.get("decision") == "block"


class DryRunRunner:
    """台本（Skill → 3役 → emit_timeline → emit_report）どおりに Hook と emit_* を呼ぶ。"""

    def __init__(self, steps: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
        self.steps = tuple(steps)

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        base = {"session_id": "dry-run", "transcript_path": "", "cwd": ""}
        data = {**base, "hook_event_name": "UserPromptSubmit", "prompt": prompt}
        for hook in _hooks(options, "UserPromptSubmit"):
            if _is_denied(await hook(data, None, {"signal": None})):
                return RunStats()
        for i, (tool_name, tool_input) in enumerate(self.steps):
            tool_use_id = f"toolu_{i:03d}"
            data = {
                **base,
                "hook_event_name": "PreToolUse",
                "tool_name": tool_name,
                "tool_input": dict(tool_input),
                "tool_use_id": tool_use_id,
            }
            results = [
                await hook(data, tool_use_id, {"signal": None})
                for hook in _hooks(options, "PreToolUse", tool_name)
            ]
            if any(_is_denied(r) for r in results):
                continue
            if tool_name == EMIT_TIMELINE_TOOL:
                handle_emit_timeline(dict(tool_input), collector)
            elif tool_name == EMIT_REPORT_TOOL:
                handle_emit_report(dict(tool_input), collector)
        return RunStats(duration_ms=0, num_turns=len(self.steps))


def _emit_args(result: ConversionResult) -> tuple[dict[str, Any], dict[str, Any]]:
    if result.timeline is None or result.picks is None:
        raise ValueError("正解ラベルから変換結果を作れない")
    timeline = result.timeline.model_dump(mode="json")
    rows = sorted(result.picks.per_symptom, key=lambda s: (s.start_date, s.term))
    return (
        {"events": timeline["events"], "contradictions": timeline["contradictions"]},
        {"per_symptom": [r.model_dump(mode="json") for r in rows]},
    )


def _prepared_like_service(
    conn: sqlite3.Connection, vid: int, settings: Settings
) -> PreparedInput:
    """service の _gather・_prepare と同じ引数で入力を作る（entry_no をそろえる）。"""
    visit = db.get_visit(conn, vid)
    if visit is None:
        raise LookupError("visit not found")
    patient = db.get_patient(conn, visit["patient_id"])
    if patient is None:
        raise LookupError("patient not found")
    return prepare_input(
        courses=db.list_courses(conn, patient["id"]),
        entries=db.list_entries(conn, patient["id"]),
        regimen_skill=load_regimen_skill(patient["regimen"], settings.skills_dir),
        report_skill=load_report_skill(skills_dir=settings.skills_dir),
        visit_date=visit["visit_date"],
        exclude_literals=(patient["id"], visit["reception_no"]),
        doctor_masks=db.list_doctor_masks(conn, vid),
    )


def dry_run_runner(
    conn: sqlite3.Connection, vid: int, settings: Settings, regimen: str
) -> DryRunRunner:
    """空の DB に seq の順で入れたので entries.id == seq（正解ラベルの entry_seq）。"""
    prepared = _prepared_like_service(conn, vid, settings)
    labels = load_labels(SYNTHETIC_DIR / f"labels_{DEMO_CASE}.json")
    timeline, report = _emit_args(result_from_labels(prepared, labels))
    agent = {"description": "変換", "prompt": "入力 JSON"}
    skill_name = load_report_skill(skills_dir=settings.skills_dir).name
    return DryRunRunner(
        [
            ("Skill", {"skill": REGIMEN_SKILL_NAMES[regimen]}),
            ("Skill", {"skill": skill_name}),
            *(("Agent", {"subagent_type": name, **agent}) for name in AGENT_NAMES),
            (EMIT_TIMELINE_TOOL, timeline),
            (EMIT_REPORT_TOOL, report),
        ]
    )


# ---------------------------------------------------------------------------
# DB の準備
# ---------------------------------------------------------------------------


def seed_demo_patient(conn: sqlite3.Connection, settings: Settings) -> SyntheticPatient:
    """表を作り Skill の版を登録し、デモ患者（コース・記録）を1つのトランザクションで入れる。"""
    db.init_db(conn)
    ensure_skill_versions(conn, settings.skills_dir)
    patient = load_patient(SYNTHETIC_DIR / f"{DEMO_CASE}.json")
    db.seed_patient(
        conn,
        patient_id=patient.patient_id,
        regimen=patient.regimen,
        courses=to_courses(patient),
        entries=sorted(to_entries(patient), key=lambda e: e.id),  # seq の順
    )
    return patient


def create_demo_visit(
    conn: sqlite3.Connection, patient: SyntheticPatient, settings: Settings
) -> int:
    """受付と同じく、今日・今コース・expires_at = now + report_ttl_hours で受診を作る。"""
    course = current_course(db.list_courses(conn, patient.patient_id), today())
    if course is None:
        raise ValueError(f"{today()} にコースが無い")
    return db.create_visit(
        conn,
        patient.patient_id,
        patient.reception_no,
        today(),
        now() + timedelta(hours=settings.report_ttl_hours),
        course.course_no,
    )


# ---------------------------------------------------------------------------
# 結果のまとめ
# ---------------------------------------------------------------------------


def hook_counts(logs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Hook ごとの allow と deny（block を含む）の回数。"""
    counter: Counter[tuple[str, str]] = Counter()
    for row in logs:
        name = row.get("hook_name")
        if name in HOOK_NAMES:
            kind = "allow" if row.get("decision") == "allow" else "deny"
            counter[(name, kind)] += 1
    return {
        name: {"allow": counter[(name, "allow")], "deny": counter[(name, "deny")]}
        for name in HOOK_NAMES
    }


def _last(logs: Sequence[Mapping[str, Any]], event: str) -> Mapping[str, Any] | None:
    found = [row for row in logs if row.get("event") == event]
    return found[-1] if found else None


def summarize(conn: sqlite3.Connection, vid: int, elapsed_s: float) -> dict[str, Any]:
    """件数・コードだけのまとめ（文面・仮名IDは入れない）。"""
    visit = db.get_visit(conn, vid) or {}
    logs = db.list_pipeline_logs(conn, "visit", vid)
    run_end = _last(logs, "run_end") or {}
    failed = _last(logs, "visit_failed") or {}
    fallback = _last(logs, "fallback") or {}
    timeline = db.get_timeline(conn, vid)
    report = db.get_report(conn, vid)
    # 組み立て直し（report_error）は run_end が ok のまま fallback だけに残る
    run_code = fallback.get("decision") or run_end.get("decision")
    return {
        "status": visit.get("status"),
        "fallback": bool(visit.get("fallback")),
        "error_code": run_code if run_code not in (None, "ok") else None,
        "failed_code": failed.get("decision"),
        "elapsed_s": round(elapsed_s, 1),
        "run_duration_ms": run_end.get("duration_ms"),
        "tokens_in": run_end.get("tokens_in"),
        "tokens_out": run_end.get("tokens_out"),
        "cost_usd": run_end.get("cost_usd"),
        "hooks": hook_counts(logs),
        "events": len(timeline.events) if timeline else None,
        "contradictions": len(timeline.contradictions) if timeline else None,
        "unprocessed": len(timeline.unprocessed_entries) if timeline else None,
        "per_symptom": len(report[1].per_symptom) if report else None,
    }


def write_outputs(conn: sqlite3.Connection, vid: int, out_dir: Path) -> list[Path]:
    """レポート HTML と timeline・ReportData の JSON を書き、書いたパスを返す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"demo-visit-{now():%Y%m%d-%H%M}"
    timeline = db.get_timeline(conn, vid)
    report = db.get_report(conn, vid)
    written: list[Path] = []
    if report is not None:
        html_path = stem.with_suffix(".html")
        html_path.write_text(report[0], encoding="utf-8")
        written.append(html_path)
    payload = {
        "timeline": timeline.model_dump(mode="json") if timeline else None,
        "report_data": report[1].model_dump(mode="json") if report else None,
    }
    json_path = stem.with_suffix(".json")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written.append(json_path)
    return written


def _show(value: Any) -> str:
    return "-" if value is None else str(value)


def print_summary(
    summary: Mapping[str, Any], reception_no: str, paths: Sequence[Path]
) -> None:
    print(f"受付番号: {reception_no}  受診日: {today()}")
    print(f"状態: {summary['status']}")
    print(f"fallback: {'あり' if summary['fallback'] else 'なし'}")
    print(f"error_code: {_show(summary['error_code'])}")
    if summary["failed_code"]:
        print(f"failed の理由: {summary['failed_code']}")
    print(
        f"所要時間: {summary['elapsed_s']} 秒"
        f"（変換 {_show(summary['run_duration_ms'])} ms）"
    )
    print(
        f"トークン: 入力 {_show(summary['tokens_in'])} / "
        f"出力 {_show(summary['tokens_out'])}  費用: {_show(summary['cost_usd'])} USD"
    )
    for name, counts in summary["hooks"].items():
        print(f"{name}: allow {counts['allow']} / deny {counts['deny']}")
    for key in ("events", "contradictions", "unprocessed", "per_symptom"):
        print(f"{key}: {_show(summary[key])}")
    for path in paths:
        print(f"出力: {path}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def run_once(settings: Settings, *, dry_run: bool, out_dir: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="tsutae-demo-visit-") as tmp:
        settings = replace(settings, db_path=Path(tmp) / "demo.db")
        conn = db.connect(settings.db_path)
        try:
            patient = seed_demo_patient(conn, settings)
            vid = create_demo_visit(conn, patient, settings)
            runner: AgentRunner = (
                dry_run_runner(conn, vid, settings, patient.regimen)
                if dry_run
                else SdkRunner()
            )
            mode = "dry-run（API を呼ばない）" if dry_run else "本物の Claude"
            print(f"生成を始める: {mode}、上限 {settings.pipeline_timeout_s:g} 秒")
            started = time.monotonic()
            await generate_visit_report(conn, vid, runner=runner, settings=settings)
            summary = summarize(conn, vid, time.monotonic() - started)
            paths = write_outputs(conn, vid, out_dir)
        finally:
            conn.close()
    print_summary(summary, patient.reception_no, paths)
    return 0 if summary["status"] == "ready" else 1


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="API を呼ばず偽物で同じ流れを通す"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="HTML と JSON の出力先"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    load_env_file()
    args = _parse(argv)
    if not args.dry_run and not has_api_key():
        print(NO_KEY_MESSAGE, file=sys.stderr)
        return 2
    os.environ.setdefault("TSUTAE_TODAY", DEFAULT_TODAY)
    return asyncio.run(
        run_once(get_settings(), dry_run=args.dry_run, out_dir=args.out_dir)
    )


if __name__ == "__main__":
    sys.exit(main())

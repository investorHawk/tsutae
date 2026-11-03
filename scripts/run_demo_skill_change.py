"""本物の Claude（SdkSkillEditor）で Skill の書き換え（D4）を1回だけ試す。

実行（先生が Claude Code のプロンプトで。サンドボックス外）:
    ! .venv/bin/python scripts/run_demo_skill_change.py [--dry-run] [--approve]
          [--skill NAME] [--request 依頼文] [--out-dir DIR]

- DB と skills_home の写し（backend/skills_home を丸ごと）を一時ディレクトリに作る。
  本体の SKILL.md には触れない。写しの今の版を skill_versions に登録し、
  `request_change` を1回 await する（上限は settings.pipeline_timeout_s）
- 終わったら状態（pending / failed）・error_code・所要時間・トークン・費用
  （pipeline_logs の run_kind=skill_change の editor_done / editor_failed）・Hook の
  発火数（H1・H3・H4・skill_check の allow / retry / deny）・差分の追加と削除の行数を出し、
  差分と新しい SKILL.md の全文を `<out-dir>/demo-skill-change-<YYYYMMDD-HHMM>.diff|.md`
  に書く（既定の out-dir は docs/eval。差分が無ければ書かない）
- `--approve`: pending なら写しの上で approve_change まで流し、新しい版の質問集
  （key と text）を出す
- `--dry-run`: SdkSkillEditor の代わりに、stomatitis の質問の後に質問を1つ足す偽の
  editor で同じ流れを通す（API を呼ばない。書き込みの後の skill_check は偽物が呼ぶ）
- ANTHROPIC_API_KEY が無く --dry-run でもなければ終了コード 2。pending（--approve なら
  承認まで成功）なら 0、それ以外は 1
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from tsutae import db
from tsutae.config import (
    REPO_ROOT,
    SKILLS_HOME,
    Settings,
    get_settings,
    has_api_key,
    load_env_file,
    now,
)
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.schemas import RunStats
from tsutae.skillchange import (
    SdkSkillEditor,
    SkillChangeError,
    SkillEditor,
    approve_change,
    request_change,
)
from tsutae.skillchange.check import make_skill_check, read_baseline
from tsutae.skillchange.editor import current_logger
from tsutae.skillchange.state import RUN_KIND
from tsutae.skills import SKILL_FILE_NAME

DEFAULT_SKILL = "regimen-folfox"
DEFAULT_REQUEST = "口内炎は、食事がとれたかも次から聞いて"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "eval"
HOOK_NAMES = ("H1", "H3", "H4", "skill_check")
DRY_RUN_KEY = "stomatitis_meal"
DRY_RUN_TEXT = "口内炎があるとき、食事はとれましたか"
_ANCHOR = "{key: stomatitis,"
NO_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY がありません。.env に書くか環境変数で渡してください。"
    "API を呼ばずに流れだけ確かめるなら --dry-run を付けてください。"
)


# ---------------------------------------------------------------------------
# 偽の editor（--dry-run。API は呼ばない）
# ---------------------------------------------------------------------------


def add_question_after_stomatitis(text: str) -> str:
    """stomatitis の質問の行の後に DRY_RUN_KEY の質問を足す（無ければそのまま）。"""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if _ANCHOR in line:
            prefix = line[: line.index(_ANCHOR)]  # "  - "
            added = (
                f"{prefix}{{key: {DRY_RUN_KEY}, text: {DRY_RUN_TEXT},"
                " answer_type: three_level}\n"
            )
            return "".join([*lines[: i + 1], added, *lines[i + 1 :]])
    return text


class DryRunSkillEditor:
    """写しの SKILL.md に質問を1つ足し、Edit の後と同じく skill_check を呼ぶ。"""

    async def edit(
        self, work_root: Path, skill_name: str, request_text: str
    ) -> RunStats:
        path = work_root / ".claude" / "skills" / skill_name / SKILL_FILE_NAME
        old = path.read_text(encoding="utf-8")
        new = add_question_after_stomatitis(old)
        if new == old:
            return RunStats(num_turns=1)
        base = read_baseline(work_root, skill_name).version
        path.write_text(new, encoding="utf-8")
        check = make_skill_check(work_root, skill_name, base, current_logger())
        data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path)},
        }
        await check(data, "toolu_dry_run", {"signal": None})
        return RunStats(num_turns=2)


# ---------------------------------------------------------------------------
# 結果のまとめ
# ---------------------------------------------------------------------------


def _kind(decision: Any) -> str:
    if decision == "allow":
        return "allow"
    if isinstance(decision, str) and decision.startswith("retry"):
        return "retry"
    return "deny"


def hook_counts(logs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Hook ごとの allow・retry（skill_check の直させ）・deny（block を含む）の回数。"""
    counter: Counter[tuple[str, str]] = Counter(
        (row["hook_name"], _kind(row.get("decision")))
        for row in logs
        if row.get("hook_name") in HOOK_NAMES
    )
    return {
        name: {k: counter[(name, k)] for k in ("allow", "retry", "deny")}
        for name in HOOK_NAMES
    }


def diff_line_counts(diff: str | None) -> tuple[int, int]:
    """unified diff の追加・削除の行数（ファイル名の行 +++ / --- は数えない）."""
    if not diff:
        return 0, 0
    lines = diff.splitlines()
    added = sum(1 for x in lines if x.startswith("+") and not x.startswith("+++"))
    removed = sum(1 for x in lines if x.startswith("-") and not x.startswith("---"))
    return added, removed


def _editor_stats(logs: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    found = [r for r in logs if r.get("event") in ("editor_done", "editor_failed")]
    return found[-1] if found else {}


def summarize(
    conn: sqlite3.Connection, change_id: int, elapsed_s: float
) -> dict[str, Any]:
    change = db.get_skill_change(conn, change_id) or {}
    logs = db.list_pipeline_logs(conn, RUN_KIND, change_id)
    stats = _editor_stats(logs)
    added, removed = diff_line_counts(change.get("diff"))
    return {
        "status": change.get("status"),
        "error_code": change.get("error_code"),
        "elapsed_s": round(elapsed_s, 1),
        "editor_duration_ms": stats.get("duration_ms"),
        "tokens_in": stats.get("tokens_in"),
        "tokens_out": stats.get("tokens_out"),
        "cost_usd": stats.get("cost_usd"),
        "hooks": hook_counts(logs),
        "added": added,
        "removed": removed,
    }


def write_outputs(change: Mapping[str, Any], out_dir: Path) -> list[Path]:
    """差分と新しい SKILL.md を書き、書いたパスを返す（差分が無ければ何も書かない）。"""
    diff, new_text = change.get("diff"), change.get("new_text")
    if not diff or new_text is None:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"demo-skill-change-{now():%Y%m%d-%H%M}"
    diff_path, md_path = stem.with_suffix(".diff"), stem.with_suffix(".md")
    diff_path.write_text(diff, encoding="utf-8")
    md_path.write_text(new_text, encoding="utf-8")
    return [diff_path, md_path]


def _show(value: Any) -> str:
    return "-" if value is None else str(value)


def print_summary(summary: Mapping[str, Any], paths: Sequence[Path]) -> None:
    print(f"状態: {_show(summary['status'])}")
    print(f"error_code: {_show(summary['error_code'])}")
    print(
        f"所要時間: {summary['elapsed_s']} 秒"
        f"（editor {_show(summary['editor_duration_ms'])} ms）"
    )
    print(
        f"トークン: 入力 {_show(summary['tokens_in'])} / "
        f"出力 {_show(summary['tokens_out'])}  費用: {_show(summary['cost_usd'])} USD"
    )
    for name, c in summary["hooks"].items():
        print(f"{name}: allow {c['allow']} / retry {c['retry']} / deny {c['deny']}")
    print(f"差分: 追加 {summary['added']} 行 / 削除 {summary['removed']} 行")
    for path in paths:
        print(f"出力: {path}")


# ---------------------------------------------------------------------------
# 承認（写しの上で）
# ---------------------------------------------------------------------------


def approve_on_copy(
    conn: sqlite3.Connection, change_id: int, skill_name: str, skills_home: Path
) -> bool:
    """写しの上で承認し、新しい版の質問集を出す。失敗は error_code を出して False。"""
    try:
        version = approve_change(conn, change_id, skills_home=skills_home)
    except SkillChangeError as exc:
        print(f"承認: 失敗 error_code: {exc.code}")
        return False
    print(f"承認: {skill_name} の版 {version}")
    saved = db.get_skill_version(conn, skill_name, version) or {}
    questions = saved.get("questions")
    if not questions:
        print("  （質問集なし）")
        return True
    for q in questions:
        print(f"  {q.key}: {q.text}")
    return True


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _editor(settings: Settings, dry_run: bool) -> SkillEditor:
    return DryRunSkillEditor() if dry_run else SdkSkillEditor(settings=settings)


async def _request_once(
    conn: sqlite3.Connection, args: argparse.Namespace, settings: Settings, home: Path
) -> int | None:
    """request_change を1回。行を作る前の失敗は error_code を出して None。"""
    try:
        return await request_change(
            conn,
            args.skill,
            args.request,
            editor=_editor(settings, args.dry_run),
            settings=settings,
            skills_home=home,
        )
    except SkillChangeError as exc:
        print("状態: -（依頼を受け付けなかった）")
        print(f"error_code: {exc.code}")
        return None


async def run_once(settings: Settings, args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="tsutae-demo-skill-change-") as tmp:
        home = Path(tmp) / "skills_home"
        shutil.copytree(SKILLS_HOME, home, symlinks=False)
        settings = replace(
            settings,
            db_path=Path(tmp) / "demo.db",
            skills_dir=home / ".claude" / "skills",
        )
        conn = db.connect(settings.db_path)
        try:
            db.init_db(conn)
            ensure_skill_versions(conn, settings.skills_dir)
            mode = "dry-run（API を呼ばない）" if args.dry_run else "本物の Claude"
            print(f"Skill: {args.skill}  依頼: {args.request}")
            print(f"書き換えを始める: {mode}、上限 {settings.pipeline_timeout_s:g} 秒")
            started = time.monotonic()
            change_id = await _request_once(conn, args, settings, home)
            if change_id is None:
                return 1
            summary = summarize(conn, change_id, time.monotonic() - started)
            change = db.get_skill_change(conn, change_id) or {}
            print_summary(summary, write_outputs(change, args.out_dir))
            if summary["status"] != "pending":
                return 1
            if args.approve and not approve_on_copy(conn, change_id, args.skill, home):
                return 1
            return 0
        finally:
            conn.close()


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API を呼ばず偽の editor で同じ流れを通す",
    )
    parser.add_argument(
        "--approve", action="store_true", help="写しの上で承認まで流し質問集を出す"
    )
    parser.add_argument(
        "--skill", default=DEFAULT_SKILL, help="書き換える Skill の名前"
    )
    parser.add_argument("--request", default=DEFAULT_REQUEST, help="医師の依頼文")
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="差分と SKILL.md の出力先"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    load_env_file()
    args = _parse(argv)
    if not args.dry_run and not has_api_key():
        print(NO_KEY_MESSAGE, file=sys.stderr)
        return 2
    return asyncio.run(run_once(get_settings(), args))


if __name__ == "__main__":
    sys.exit(main())

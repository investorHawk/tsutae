"""本物の Claude で D4 レジメン（FOLFIRI＋BV）を新しいレジメンとしてチャットで作る通し。

実行（先生が Claude Code のプロンプトで。サンドボックス外）:
    ! .venv/bin/python scripts/run_demo_regimen.py [--json] [--adopt]
          [--text 最初の文] [--max-turns N] [--out-dir DIR]

- DB と skills_home の写し（backend/skills_home を丸ごと）を一時ディレクトリに作り、
  そこを指したアプリ（`create_app`）に TestClient で医師 API を呼ぶ。本物の
  backend/skills_home と data/ の DB には触れない（`--adopt` でも写しの上で採用する）
- 流れ: `POST /api/doctor/regimen-drafts {from: "new"}` → `POST .../turns {text}` を
  数往復 → `GET .../preview` →（`--adopt` のときだけ）`POST .../adopt` →
  `GET /api/doctor/regimens`（患者の登録の選択肢に出るか）
- 往復の文は決まった順: 1. 最初の文（`--text`。既定は plan §5 の FOLFIRI＋BV）。
  2. その後は、Claude が聞いていれば（ask）選択肢の1つ目で答える／質問の提案をまだ頼んで
  いなければ「質問を提案して」／未入力が残れば「標準の値で埋めて」。未入力が 0 で質問の
  提案が済めば止める。往復は `--max-turns`（既定 6）まで
- 往復ごとに秒・費用・トークン（`regimen_chat` のログの turn_end。ResultMessage の
  total_cost_usd など）・ツールの呼び出しと拒否・H4 の拒否・変えた欄・AI の欄（標準の値）・未入力・
  ask・提案した質問・失敗のコードを表で出す。往復が失敗したらそこで止める
- `--json`: `<out-dir>/demo-regimen-<YYYYMMDD-HHMM>.json`（往復の数字・会話・最後の
  フォーム・確認の結果・上限の設定）と、描けたら同じ名前の `.md`（SKILL.md の全文）を書く
  （既定の out-dir は docs/eval）。会話の文は院内の画面に出る文で、患者のデータは無い
- ANTHROPIC_API_KEY が無ければ終了コード 2。全ての往復が成功し確認の検査に掛からず
  （`--adopt` なら採用して選択肢に出れば）0、それ以外は 1
- 症例は全て合成。薬の量は扱わない
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tsutae import db
from tsutae.api.app import create_app
from tsutae.api.deps import DOCTOR_COOKIE, make_doctor_token
from tsutae.config import (
    REPO_ROOT,
    SKILLS_HOME,
    Settings,
    get_settings,
    has_api_key,
    load_env_file,
    now,
)
from tsutae.regimen.chat_sdk import SdkRegimenChat
from tsutae.regimen.chat_turn import RUN_KIND

ChatFactory = Callable[[Settings], Any]

DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "eval"
DEFAULT_MAX_TURNS = 6
BASE = "/api/doctor/regimen-drafts"
DEFAULT_TEXT = (
    "FOLFIRI＋BV を作りたい。大腸がん、14日ごと。"
    "ベバシズマブ・イリノテカン・レボホリナート・フルオロウラシル急速静注を Day1 に点滴、"
    "フルオロウラシル46時間を持続ポンプで Day1〜3"
)
PROPOSE_TEXT = (
    "患者への質問を提案してください。足りない欄があれば標準の値で埋めてください"
)
FILL_TEXT = "まだ空いている欄を標準の値で埋めてください"
KIND_LABELS = {
    "request": "依頼",
    "answer": "答え",
    "propose": "質問の提案",
    "fill": "埋める",
}
NO_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY がありません。.env に書くか環境変数で渡してください。"
    "このスクリプトは本物の Claude を呼びます（API を呼ばない確かめは "
    "backend/tests/test_run_demo_regimen.py）。"
)


def answer_text(option: str) -> str:
    """Claude の ask に選択肢で答える文。"""
    return f"「{option}」でお願いします"


# ---------------------------------------------------------------------------
# 往復の記録
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    n: int
    kind: str
    text: str
    elapsed_s: float = 0.0
    status_code: int = 200
    turn_error: str | None = None
    duration_ms: int | None = None
    cost_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    sdk_turns: int | None = None
    tool_calls: int = 0
    tool_rejected: int = 0
    h4_denied: int = 0
    changed: int = 0
    ai_fields: int = 0
    missing: int = 0
    ask: dict[str, Any] | None = None
    proposed: list[str] = field(default_factory=list)
    reply: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _counts(decision: str | None) -> dict[str, int]:
    """turn_counts の `calls:N:rejected:N:turns:N:changed:N` を読む。"""
    parts = (decision or "").split(":")
    pairs = zip(parts[::2], parts[1::2], strict=False)
    return {k: int(v) for k, v in pairs if v.isdigit()}


def apply_logs(turn: Turn, logs: Sequence[Mapping[str, Any]]) -> Turn:
    """1往復のログ（regimen_chat。文面は無い）から数字を写す。"""
    ends = [r for r in logs if r.get("event") == "turn_end"]
    counts = [r for r in logs if r.get("event") == "turn_counts"]
    end = ends[-1] if ends else {}
    got = _counts(counts[-1].get("decision")) if counts else {}
    h4 = [r for r in logs if r.get("hook_name") == "H4"]
    tools = [r for r in logs if r.get("event") == "regimen_tool"]
    return replace(
        turn,
        duration_ms=end.get("duration_ms"),
        cost_usd=end.get("cost_usd"),
        tokens_in=end.get("tokens_in"),
        tokens_out=end.get("tokens_out"),
        sdk_turns=got.get("turns"),
        tool_calls=got.get("calls", len(tools)),
        tool_rejected=got.get(
            "rejected",
            sum(1 for r in tools if str(r.get("decision")).startswith("reject")),
        ),
        h4_denied=sum(1 for r in h4 if r.get("decision") != "allow"),
    )


def apply_draft(turn: Turn, draft: Mapping[str, Any]) -> Turn:
    """往復の後の下書きから、変えた欄・AI の欄（標準の値）・未入力・ask・提案を写す。"""
    chat = draft.get("chat") or []
    last = chat[-1] if chat else {}
    mine = last.get("role") == "assistant" and last.get("generation") == draft.get(
        "generation"
    )
    sources = draft.get("sources") or {}
    return replace(
        turn,
        changed=len(last.get("changed") or []) if mine else 0,
        ai_fields=sum(1 for v in sources.values() if v == "standard"),
        missing=len(draft.get("missing") or []),
        ask=last.get("ask") if mine else None,
        proposed=list(last.get("proposed") or []) if mine else [],
        reply=last.get("text") if mine else None,
    )


def next_step(
    turns: Sequence[Turn], draft: Mapping[str, Any]
) -> tuple[str, str] | None:
    """次に送る（種類, 文）。止めるなら None。"""
    last = turns[-1]
    if last.ask and last.ask.get("options"):
        return "answer", answer_text(str(last.ask["options"][0]))
    # 提案を1回頼んだら（何も足されなくても）もう頼まない（同じ文で回り続けない）
    proposed = any(t.proposed or t.kind == "propose" for t in turns)
    if not proposed:
        return "propose", PROPOSE_TEXT
    if draft.get("missing"):
        return "fill", FILL_TEXT
    return None


def totals(turns: Sequence[Turn]) -> dict[str, Any]:
    def total(name: str) -> Any:
        values = [getattr(t, name) for t in turns if getattr(t, name) is not None]
        return round(sum(values), 6) if values else None

    return {
        "turns": len(turns),
        "elapsed_s": round(sum(t.elapsed_s for t in turns), 1),
        "cost_usd": total("cost_usd"),
        "tokens_in": total("tokens_in"),
        "tokens_out": total("tokens_out"),
        "sdk_turns_max": max((t.sdk_turns or 0 for t in turns), default=0),
        "tool_calls": sum(t.tool_calls for t in turns),
        "tool_rejected": sum(t.tool_rejected for t in turns),
        "h4_denied": sum(t.h4_denied for t in turns),
        "asks": sum(1 for t in turns if t.ask),
        "proposed": sum(len(t.proposed) for t in turns),
    }


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------


def _show(value: Any) -> str:
    return "-" if value is None else str(value)


def _short(text: str | None, limit: int = 120) -> str:
    if not text:
        return "-"
    one = " ".join(text.split())
    return one if len(one) <= limit else one[:limit] + "…"


TABLE_HEAD = (
    "| # | 種類 | 秒 | 費用 USD | トークン 入/出 | SDK の回数 | ツール | 拒否 ツール/H4 "
    "| 変えた欄 | AI の欄（標準の値） | 未入力 | ask | 提案した質問 | 失敗 |"
)


def table_row(t: Turn) -> str:
    cells = [
        str(t.n),
        KIND_LABELS.get(t.kind, t.kind),
        f"{t.elapsed_s:.1f}",
        _show(t.cost_usd),
        f"{_show(t.tokens_in)}/{_show(t.tokens_out)}",
        _show(t.sdk_turns),
        str(t.tool_calls),
        f"{t.tool_rejected}/{t.h4_denied}",
        str(t.changed),
        str(t.ai_fields),
        str(t.missing),
        "1" if t.ask else "0",
        "、".join(t.proposed) or "-",
        _show(t.turn_error),
    ]
    return "| " + " | ".join(cells) + " |"


def print_table(turns: Sequence[Turn]) -> None:
    print()
    print(TABLE_HEAD)
    print("|" + "---|" * 14)
    for t in turns:
        print(table_row(t))
    s = totals(turns)
    print(
        f"計: {s['turns']} 往復・{s['elapsed_s']} 秒・費用 {_show(s['cost_usd'])} USD・"
        f"ツール {s['tool_calls']} 回（拒否 {s['tool_rejected']}）・"
        f"H4 の拒否 {s['h4_denied']}・ask {s['asks']}・提案した質問 {s['proposed']}"
    )


# ---------------------------------------------------------------------------
# 通し
# ---------------------------------------------------------------------------


@dataclass
class Run:
    settings: Settings
    turns: list[Turn] = field(default_factory=list)
    draft: dict[str, Any] = field(default_factory=dict)
    preview: dict[str, Any] | None = None
    adopted: dict[str, Any] | None = None
    error: str | None = None


def _logs(settings: Settings, draft_id: int) -> list[dict[str, Any]]:
    conn = db.connect(settings.db_path)
    try:
        return db.list_pipeline_logs(conn, RUN_KIND, draft_id)
    finally:
        conn.close()


def _error_of(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"http_{response.status_code}"
    return str(body.get("error") or body.get("detail") or response.status_code)


def one_turn(client: TestClient, run: Run, kind: str, text: str) -> Turn:
    draft_id = int(run.draft["id"])
    before = len(_logs(run.settings, draft_id))
    turn = Turn(n=len(run.turns) + 1, kind=kind, text=text)
    print(f"→ 先生（{KIND_LABELS.get(kind, kind)}）: {_short(text)}")
    started = time.monotonic()
    response = client.post(f"{BASE}/{draft_id}/turns", json={"text": text})
    turn = replace(turn, elapsed_s=round(time.monotonic() - started, 1))
    turn = apply_logs(turn, _logs(run.settings, draft_id)[before:])
    if response.status_code != 200:
        return replace(
            turn, status_code=response.status_code, turn_error=_error_of(response)
        )
    body = response.json()
    run.draft = body["draft"]
    turn = apply_draft(replace(turn, turn_error=body.get("turn_error")), run.draft)
    print(f"← Claude: {_short(turn.reply)}")
    if turn.ask:
        print(f"   聞いています: {_short(turn.ask.get('question'))}")
    return turn


def chat_loop(client: TestClient, run: Run, first_text: str, max_turns: int) -> None:
    step: tuple[str, str] | None = ("request", first_text)
    while step is not None and len(run.turns) < max_turns:
        turn = one_turn(client, run, *step)
        run.turns.append(turn)
        if turn.turn_error is not None:
            run.error = turn.turn_error
            return
        step = next_step(run.turns, run.draft)


def show_preview(client: TestClient, run: Run) -> None:
    response = client.get(f"{BASE}/{run.draft['id']}/preview")
    if response.status_code != 200:
        run.error = run.error or _error_of(response)
        print(f"確認: 取れなかった（{_error_of(response)}）")
        return
    run.preview = response.json()
    p = run.preview
    md = skill_text(p)
    print(
        f"確認: {_show(p.get('skill_name'))} 版 {_show(p.get('version'))}・"
        f"AI が入れた値（標準の値） {len(p.get('ai_values') or [])} 欄・"
        f"検査の欠け {len(p.get('issues') or [])}・"
        f"SKILL.md {len(md.splitlines()) if md else '-'} 行"
    )
    for issue in p.get("issues") or []:
        print(f"  欠け: {issue.get('field_id')} {issue.get('code')}")


def adopt_on_copy(client: TestClient, run: Run) -> None:
    p = run.preview or {}
    response = client.post(
        f"{BASE}/{run.draft['id']}/adopt",
        json={"confirm_token": p.get("confirm_token"), "ai_values_confirmed": True},
    )
    if response.status_code != 200:
        run.error = _error_of(response)
        print(f"採用: 失敗（{run.error}）")
        return
    body = response.json()
    choices = client.get("/api/doctor/regimens").json().get("regimens", [])
    found = next((c for c in choices if c.get("code") == body.get("regimen")), None)
    run.adopted = {**body, "in_choices": found is not None}
    print(f"採用: {body['skill_name']} 版 {body['version']}（一時の写しの上）")
    if found is None:
        run.error = "not_in_choices"
        print(f"患者の登録の選択肢: {body.get('regimen')} が無い")
        return
    label = found.get("display_name") or found.get("code")
    print(f"患者の登録の選択肢: {found.get('code')}（{label}）がある")


def skill_text(preview: Mapping[str, Any] | None) -> str | None:
    """確認の SKILL.md の文（新規は全文。既存の版の下書きなら diff）。"""
    md = (preview or {}).get("skill_md")
    text = md.get("text") if isinstance(md, Mapping) else None
    return text if isinstance(text, str) and text else None


def _status(run: Run) -> str:
    if run.error is not None:
        return "failed"
    if run.preview is None or run.preview.get("issues"):
        return "incomplete"
    return "ok"


def result_json(run: Run, args: argparse.Namespace) -> dict[str, Any]:
    s = run.settings
    draft = run.draft
    preview = run.preview or {}
    return {
        "kind": "demo-regimen",
        "note": "症例は全て合成。会話の文は院内の画面に出る文（患者のデータは無い）",
        "at": now().isoformat(),
        "model": s.model,
        "status": _status(run),
        "error": run.error,
        "limits": {
            "regimen_max_turns": s.regimen_max_turns,
            "regimen_max_budget_usd": s.regimen_max_budget_usd,
            "regimen_turn_timeout_s": s.regimen_turn_timeout_s,
            "script_max_turns": args.max_turns,
        },
        "turns": [t.to_json() for t in run.turns],
        "totals": totals(run.turns),
        "preview": (
            None
            if run.preview is None
            else {
                "skill_name": preview.get("skill_name"),
                "version": preview.get("version"),
                "ai_values": len(preview.get("ai_values") or []),
                "issues": preview.get("issues") or [],
                "skill_md_lines": (
                    len(md.splitlines()) if (md := skill_text(preview)) else None
                ),
            }
        ),
        "adopt": run.adopted,
        "form": draft.get("form"),
        "sources": draft.get("sources"),
    }


def write_outputs(run: Run, args: argparse.Namespace) -> list[Path]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.out_dir / f"demo-regimen-{now():%Y%m%d-%H%M}"
    json_path = stem.with_suffix(".json")
    data = result_json(run, args)
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    paths = [json_path]
    md = skill_text(run.preview)
    if md:
        md_path = stem.with_suffix(".md")
        md_path.write_text(md, encoding="utf-8")
        paths.append(md_path)
    return paths


def _settings_on_copy(base: Settings, tmp: Path) -> Settings:
    home = tmp / "skills_home"
    shutil.copytree(SKILLS_HOME, home, symlinks=False)
    return replace(
        base,
        db_path=tmp / "demo.db",
        skills_dir=home / ".claude" / "skills",
        secret_key=secrets.token_urlsafe(32),
        doctor_password=secrets.token_urlsafe(16),
        public_base_url="http://127.0.0.1:8000",
    )


def _start(client: TestClient, run: Run) -> bool:
    token = make_doctor_token(run.settings.secret_key, now())
    client.cookies.set(DOCTOR_COOKIE, token)
    response = client.post(BASE, json={"from": "new"})
    if response.status_code != 200:
        run.error = _error_of(response)
        print(f"下書き: 作れなかった（{run.error}）")
        return False
    run.draft = response.json()["draft"]
    print(f"下書き: 新しいレジメン（id {run.draft['id']}）")
    return True


def run_once(
    base: Settings, args: argparse.Namespace, chat_factory: ChatFactory
) -> int:
    with tempfile.TemporaryDirectory(prefix="tsutae-demo-regimen-") as tmp:
        settings = _settings_on_copy(base, Path(tmp))
        run = Run(settings=settings)
        app = create_app(settings, regimen_chat=chat_factory(settings))
        print(
            f"D4 レジメンの通し: 上限 1往復 {settings.regimen_turn_timeout_s:g} 秒・"
            f"{settings.regimen_max_turns} 回・{settings.regimen_max_budget_usd:g} USD"
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            if _start(client, run):
                chat_loop(client, run, args.text, args.max_turns)
                print_table(run.turns)
                print(f"未入力: {len(run.draft.get('missing') or [])}")
                show_preview(client, run)
                _maybe_adopt(client, run, args.adopt)
        for path in write_outputs(run, args) if args.json else []:
            print(f"出力: {path}")
        ok = _status(run) == "ok" and (not args.adopt or run.adopted is not None)
        return 0 if ok else 1


def _maybe_adopt(client: TestClient, run: Run, adopt: bool) -> None:
    if not adopt:
        print("採用: しない（--adopt を付けると一時の写しの上で採用する）")
    elif run.error is not None:
        print(f"採用: しない（往復が失敗した: {run.error}）")
    elif run.preview is None or run.preview.get("issues"):
        print("採用: しない（確認の検査に掛かった）")
    else:
        adopt_on_copy(client, run)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--text", default=DEFAULT_TEXT, help="最初に送る先生の文")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help="送る往復の数の上限（費用を抑える）",
    )
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="一時の写しの上で採用し、患者の登録の選択肢に出るか確かめる",
    )
    parser.add_argument(
        "--json", action="store_true", help="結果の JSON と SKILL.md を out-dir に書く"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="--json の出力先"
    )
    args = parser.parse_args(argv)
    if args.max_turns < 1:
        parser.error("--max-turns は 1 以上")
    return args


def _sdk_chat(settings: Settings) -> Any:
    return SdkRegimenChat(settings)


def main(
    argv: Sequence[str] | None = None, *, chat_factory: ChatFactory | None = None
) -> int:
    """chat_factory を渡すと Claude の代わりにそれを使う（テスト用。キーは見ない）。"""
    load_env_file()
    args = _parse(argv)
    if chat_factory is None and not has_api_key():
        print(NO_KEY_MESSAGE, file=sys.stderr)
        return 2
    return run_once(get_settings(), args, chat_factory or _sdk_chat)


if __name__ == "__main__":
    sys.exit(main())

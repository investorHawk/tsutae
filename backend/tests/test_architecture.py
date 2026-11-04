"""アーキテクチャの検査（ast。docs/architecture.md §0-10・§8・§8b）。

- 患者 API（`tsutae/api/patient.py`）は pipeline・report・変換結果（get_timeline・
  get_report）・skillchange を import しない
- 患者側の API（`patient.py`・`visit.py`・`fixed_rules.py`）は変換結果の読み書き
  （`db.get_report` 等の属性参照・名前・`getattr` の文字列・reports/timelines を引く
  SQL）を使わない（`from tsutae import db` 経由の抜け道を塞ぐ）
- 実際の患者 API の応答（spec §18）: AI の出力（用語・引用・レポート）と医師向けの
  語を含まない。文字列は patient_strings.json・Skill の質問文・本人の記録・機械の
  コード（日時・状態・キー）だけ
- `tsutae/` のどこにも `datetime.now(` の直接呼び出しが無い（config.py を除く。
  時計は `tsutae.config.now()` / `today()` を使う）
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tsutae.config import PACKAGE_ROOT, PATIENT_STRINGS_PATH

PATIENT_API = PACKAGE_ROOT / "api" / "patient.py"
CLOCK_MODULE = PACKAGE_ROOT / "config.py"
FORBIDDEN_MODULES = ("tsutae.pipeline", "tsutae.report", "tsutae.skillchange")
FORBIDDEN_NAMES = frozenset({"get_timeline", "get_report", "skillchange"})
# 患者側の API。visit.py は生成を起こすため pipeline.service の import は許す
PATIENT_SIDE = tuple(
    PACKAGE_ROOT / "api" / name for name in ("patient.py", "visit.py", "fixed_rules.py")
)
RESULT_ACCESSORS = frozenset(
    {"get_timeline", "get_report", "save_timeline", "save_report"}
)
RESULT_SQL = re.compile(
    r"\b(?:from|join|into|update|table)\s+[\"'`\[]?(?:reports|timelines)\b",
    re.IGNORECASE,
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _resolve(node: ast.ImportFrom, path: Path) -> str:
    """相対 import を `tsutae.` からの絶対名に直す。"""
    if node.level == 0:
        return node.module or ""
    package = path.parent.relative_to(PACKAGE_ROOT.parent).parts
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def imported(path: Path, located: Path | None = None) -> list[tuple[str, str | None]]:
    """(モジュール名, 取り込んだ名前) の一覧。`import x` の名前は None。

    関数の中の import も数える。相対 import は located（既定は path）の位置で解決する。
    """
    where = located or path
    found: list[tuple[str, str | None]] = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            found.extend((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve(node, where)
            found.extend((module, alias.name) for alias in node.names)
    return found


def _is_forbidden(module: str, name: str | None) -> bool:
    full = f"{module}.{name}" if name else module
    if any(
        full == bad or full.startswith(bad + ".") or module.startswith(bad + ".")
        for bad in FORBIDDEN_MODULES
    ):
        return True
    return name in FORBIDDEN_NAMES or module.split(".")[-1] in FORBIDDEN_NAMES


def forbidden_imports(path: Path, located: Path | None = None) -> list[str]:
    return [
        f"{module}.{name}" if name else module
        for module, name in imported(path, located)
        if _is_forbidden(module, name)
    ]


def _is_datetime(node: ast.expr) -> bool:
    """`datetime` か `<何か>.datetime`（`datetime.datetime`）。"""
    if isinstance(node, ast.Name):
        return node.id == "datetime"
    return isinstance(node, ast.Attribute) and node.attr == "datetime"


def direct_now_calls(path: Path) -> list[int]:
    """`datetime.now(...)`・`datetime.datetime.now(...)` の行番号。"""
    return [
        node.lineno
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "now"
        and _is_datetime(node.func.value)
    ]


def _package_files() -> Iterator[Path]:
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


# ---------------------------------------------------------------------------
# 患者 API の import
# ---------------------------------------------------------------------------


def test_patient_api_does_not_import_results_or_pipeline() -> None:
    assert PATIENT_API.is_file()
    assert forbidden_imports(PATIENT_API) == []


@pytest.mark.parametrize(
    "source",
    [
        "import tsutae.pipeline\n",
        "import tsutae.pipeline.service as s\n",
        "from tsutae.pipeline import service\n",
        "from tsutae.pipeline.service import generate_visit_report\n",
        "from tsutae import pipeline\n",
        "from tsutae import report\n",
        "from tsutae.report import render_report_html\n",
        "from tsutae.db import get_timeline\n",
        "from tsutae.db.repo_visits import get_report\n",
        "from tsutae import skillchange\n",
        "from tsutae.skillchange import request_change\n",
        "from ..pipeline import service\n",
        "from .. import report\n",
        "def f():\n    from tsutae.db import get_report\n",
    ],
)
def test_forbidden_import_detector_catches(tmp_path: Path, source: str) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    # 相対 import は api/ の中のファイルとして解決する
    assert forbidden_imports(probe, located=PATIENT_API), source


def test_allowed_imports_pass(tmp_path: Path) -> None:
    probe = tmp_path / "ok.py"
    probe.write_text(
        "from tsutae import db\n"
        "from tsutae.db import get_entry, list_entries\n"
        "from tsutae.skills import load_regimen_skill\n"
        "from tsutae.api.deps import ApiError\n",
        encoding="utf-8",
    )
    assert forbidden_imports(probe) == []


# ---------------------------------------------------------------------------
# 患者側の API の変換結果の参照（import 以外の経路）
# ---------------------------------------------------------------------------


def _result_reference(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in RESULT_ACCESSORS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in RESULT_ACCESSORS:
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value in RESULT_ACCESSORS:
            return node.value  # getattr(db, "get_report") など
        if RESULT_SQL.search(node.value):
            return "sql:" + RESULT_SQL.search(node.value).group(0)
    return None


def result_references(path: Path) -> list[tuple[int, str]]:
    """変換結果を読み書きする参照の (行, 名前)。"""
    found = []
    for node in ast.walk(_parse(path)):
        name = _result_reference(node)
        if name is not None:
            found.append((getattr(node, "lineno", 0), name))
    return sorted(found)


@pytest.mark.parametrize("path", PATIENT_SIDE, ids=lambda p: p.name)
def test_patient_side_api_does_not_touch_results(path: Path) -> None:
    assert path.is_file()
    assert result_references(path) == []


def test_fixed_rules_does_not_import_results_or_pipeline() -> None:
    assert forbidden_imports(PATIENT_SIDE[2]) == []


@pytest.mark.parametrize(
    "source",
    [
        "from tsutae import db\nx = db.get_report(conn, 1)\n",
        "from tsutae import db\nx = db.get_timeline(conn, 1)\n",
        "import tsutae.db as d\nd.save_report(conn, 1, '', data)\n",
        "from tsutae import db as storage\nf = storage.get_timeline\n",
        "from tsutae import db\nf = getattr(db, 'get_report')\n",
        "def f(conn):\n    return conn.execute('SELECT html FROM reports')\n",
        "q = 'select json from timelines where visit_id = ?'\n",
        "q = 'SELECT * FROM visits v JOIN \"reports\" r ON r.visit_id = v.id'\n",
    ],
)
def test_result_reference_detector_catches(tmp_path: Path, source: str) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    assert result_references(probe), source


def test_result_reference_detector_allows(tmp_path: Path) -> None:
    probe = tmp_path / "ok.py"
    probe.write_text(
        "from tsutae import db\n"
        "e = db.get_entry(conn, 1)\n"
        "v = db.get_visit(conn, 1)\n"
        "msg = 'reports are printed by the doctor'\n",
        encoding="utf-8",
    )
    assert result_references(probe) == []


# ---------------------------------------------------------------------------
# datetime.now( の直接呼び出し
# ---------------------------------------------------------------------------


def test_no_direct_datetime_now_outside_config() -> None:
    offenders = {
        str(path.relative_to(PACKAGE_ROOT)): lines
        for path in _package_files()
        if path != CLOCK_MODULE and (lines := direct_now_calls(path))
    }
    assert offenders == {}


def test_config_is_the_clock() -> None:
    """検出器が働くこと（config.py には datetime.now( がある）。"""
    assert direct_now_calls(CLOCK_MODULE)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("from datetime import datetime\nx = datetime.now()\n", [2]),
        ("import datetime\nx = datetime.datetime.now(tz)\n", [2]),
        ("import datetime as dt\nx = dt.datetime.now()\n", [2]),
        ("from tsutae.config import now\nx = now()\n", []),
        ("from tsutae.config import now as clock_now\nx = clock_now()\n", []),
        ("x = obj.now()\n", []),
    ],
)
def test_direct_now_detector(tmp_path: Path, source: str, expected: list[int]) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    assert direct_now_calls(probe) == expected


# ---------------------------------------------------------------------------
# 実際の患者 API の応答（spec §18。AI の出力・医師向けの語を返さない）
# ---------------------------------------------------------------------------

DOCTOR_ONLY_WORDS = (
    "Grade",
    "grade",
    "軽症",
    "中等症",
    "重症",
    "重篤",
    "AI変換",
    "有害事象",
    "CTCAE",
    "未処理",
    "伏せ字",
    "[病院]",
    "[伏せ字]",
    "[ID]",
    "○○",
    "<html",
    "<table",
)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?\+09:00)?")
CODE = re.compile(r"[a-z][a-z0-9_.-]*(@[1-9][0-9]*)?")


def _strings_in(value: Any) -> Iterator[tuple[str | None, str]]:
    """JSON の中の (親のキー, 文字列の値)。キーそのものは構造なので数えない。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                yield key, item
            else:
                yield from _strings_in(item)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield None, item
            else:
                yield from _strings_in(item)


def _ai_artifacts(timeline: Any, report: tuple[str, Any]) -> set[str]:
    found = {report[0]}
    for event in timeline.events:
        found.update({event.term, event.source_quote})
    for c in timeline.contradictions:
        found.add(c.free_text_quote)
    for pick in report[1].per_symptom:
        found.update({pick.term, pick.representative_quote})
    return found


def _patient_responses(client: Any, pid: str, other: str) -> list[Any]:
    """患者が叩く経路を一通り（成功と失敗）呼んだ応答。"""
    fever = {"question_key": "fever", "value": "measured", "temperature": 38.4}
    entry = {"answers": [fever], "free_text": "夜に熱っぽかった"}
    return [
        client.post("/api/patient/register", json={"pid": pid}),
        client.post("/api/patient/register", json={"pid": "P-ZZZZ9999"}),
        client.get("/api/patient/strings"),
        client.get(f"/api/patient/{pid}/questions"),
        client.get(f"/api/patient/{pid}/entries"),
        client.post(f"/api/patient/{pid}/entries", json=entry),
        client.post(f"/api/patient/{pid}/entries", json={"answers": "x"}),
        client.get(f"/api/patient/{other}/questions"),
        client.get(f"/api/patient/{other}/entries"),
        client.post(f"/api/patient/{pid}/entries/999999/undo"),
        client.post("/api/visit", json={"reception_no": "A-024"}),
        client.post("/api/visit", json={"reception_no": ""}),
    ]


def _allowed_strings(conn: Any, pid: str, settings: Any) -> set[str]:
    from tsutae import db
    from tsutae.skills import load_regimen_skill

    strings = json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))
    allowed = {pid, *strings, *strings.values()}
    for regimen in ("FOLFOX", "CAPOX"):
        skill = load_regimen_skill(regimen, settings.skills_dir)
        allowed.update(q.text for q in skill.questions)
    allowed.update(e.free_text for e in db.list_entries(conn, pid) if e.free_text)
    return allowed


def _is_machine_code(value: str) -> bool:
    return bool(ISO_DATE.fullmatch(value) or CODE.fullmatch(value))


def response_violations(
    text: str, body: Any, allowed: set[str], artifacts: set[str]
) -> list[str]:
    """医師向けの語・許されていない文字列・AI の出力（本人の記録と同じものは除く）。"""
    words = [w for w in DOCTOR_ONLY_WORDS if w in text]
    values = [v for _k, v in _strings_in(body)]
    stray = [v for v in values if v not in allowed and not _is_machine_code(v)]
    leaked = [v for v in values if v in artifacts and v not in allowed]
    return words + stray + leaked


def test_response_checker_flags_leaks() -> None:
    allowed = {"なし", "P-DEMO0001"}
    artifacts = {"下痢", "おなかがゆるい"}
    body = {"id": "P-DEMO0001", "x": ["なし", "下痢"], "y": {"z": "Grade 2"}}
    found = response_violations(
        json.dumps(body, ensure_ascii=False), body, allowed, artifacts
    )
    assert "Grade" in found and "下痢" in found and "Grade 2" in found
    ok = {"id": "P-DEMO0001", "value": "none", "at": "2026-11-09T09:30:00+09:00"}
    assert response_violations(json.dumps(ok), ok, allowed, artifacts) == []


def test_patient_responses_have_no_ai_output_or_doctor_wording(
    tmp_path: Path, fixed_today: str
) -> None:
    from api_helpers import api_client, db_conn, register, seed_synthetic
    from pipeline_fakes import FakeRunner, label_payloads, prepare_case, standard_steps

    from tsutae import db

    prepared = prepare_case("demo_patient")
    timeline, report = label_payloads("demo_patient", prepared)
    runner = FakeRunner(standard_steps(timeline, report))
    with api_client(tmp_path, runner=runner) as client:
        pids = seed_synthetic(client.app)
        pid, other = "P-DEMO0001", next(p for p in pids if p != "P-DEMO0001")
        register(client, pid)
        assert client.post("/api/visit", json={"reception_no": "A-023"}).is_success
        with db_conn(client.app) as conn:
            (visit,) = db.list_visits(conn)
            saved = db.get_timeline(conn, visit["id"])
            artifacts = _ai_artifacts(saved, db.get_report(conn, visit["id"]))
        assert visit["fallback"] == 0 and saved is not None and saved.events
        responses = _patient_responses(client, pid, other)
        with db_conn(client.app) as conn:
            allowed = _allowed_strings(conn, pid, client.app.state.settings)
    assert {r.status_code for r in responses} >= {200, 403, 404, 422}
    assert artifacts - allowed  # AI の出力が DB にあり、検査に意味がある
    for r in responses:
        assert response_violations(r.text, r.json(), allowed, artifacts) == [], r.url

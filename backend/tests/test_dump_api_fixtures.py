"""scripts/dump_api_fixtures.py: フロントの契約テスト用の API 応答（fixture）。

- 書いてある fixture が今の API の出力と一致すること（古くなっていないこと）
- 日時・仮名ID が固定され、2回作っても同じになること
- 患者 API・医師 API の全経路（成功と代表的な失敗）があること
- 本物の Skill（backend/skills_home）を書き換えないこと
- 印刷の経路 GET /api/doctor/visits/{id}/report（text/html。JSON の fixture とは別枠）が
  200・text/html・Cache-Control: no-store・CSP を返し、未認証は 401・無い受診は 404
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from tsutae.config import REPO_ROOT, SKILLS_DIR

SCRIPT = REPO_ROOT / "scripts" / "dump_api_fixtures.py"
FIXTURE_DIR = REPO_ROOT / "frontend" / "src" / "test" / "fixtures" / "api"
ENVELOPE_KEYS = {"method", "path", "request", "status", "body"}


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dump_api_fixtures", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass が自分のモジュールを引く
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


@pytest.fixture(scope="module")
def dump(script: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> Any:
    return script.build_dump(tmp_path_factory.mktemp("dump"))


@pytest.fixture(scope="module")
def generated(dump: Any) -> dict[str, Any]:
    return dump.fixtures


def _committed() -> dict[str, Any]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(FIXTURE_DIR.glob("*.json"))
    }


def test_committed_fixtures_are_up_to_date(generated: dict[str, Any]) -> None:
    committed = _committed()
    assert sorted(committed) == sorted(
        generated
    ), "fixture の一覧が違う。scripts/dump_api_fixtures.py を流し直す"
    stale = [name for name in generated if committed[name] != generated[name]]
    assert stale == [], f"古い fixture: {stale}（dump_api_fixtures.py を流し直す）"


def test_committed_files_are_formatted(script: ModuleType) -> None:
    """ファイルは render の出力そのもの（手で直していない）。"""
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert path.read_text(encoding="utf-8") == script.render(data), path.name


def test_generation_is_deterministic(
    script: ModuleType,
    generated: dict[str, Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    again = script.build_fixtures(tmp_path_factory.mktemp("dump-again"))
    assert again == generated


def test_envelopes_have_the_same_shape(generated: dict[str, Any]) -> None:
    for name, envelope in generated.items():
        assert set(envelope) == ENVELOPE_KEYS, name
        assert envelope["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE"), name
        assert envelope["path"].startswith("/api/"), name
        assert isinstance(envelope["status"], int), name
        if envelope["status"] >= 400:
            # D4 レジメンの検査の失敗だけは欄の id と理由（issues）を添える
            keys = set(envelope["body"])
            assert keys in ({"error"}, {"error", "issues"}), name


def test_json_routes_match_the_app(script: ModuleType, tmp_path: Path) -> None:
    """JSON_ROUTES はアプリに載っている経路（レポートの HTML を除く）と同じ。"""
    from api_helpers import make_app

    assert script.app_json_routes(make_app(tmp_path)) == script.JSON_ROUTES


def test_every_route_has_a_success_fixture(
    script: ModuleType, generated: dict[str, Any]
) -> None:
    """§8 の JSON の経路は全て成功の fixture を持つ（レポートの HTML を除く）。"""
    templates = {
        (env["method"], script.route_template(env["path"]))
        for env in generated.values()
        if env["status"] < 400
    }
    assert templates >= script.JSON_ROUTES


def test_representative_failures(generated: dict[str, Any]) -> None:
    errors = {
        (env["status"], env["body"]["error"])
        for env in generated.values()
        if env["status"] >= 400
    }
    assert errors >= {
        (401, "not_logged_in"),
        (401, "bad_password"),
        (403, "forbidden"),
        (404, "unknown_patient"),
        (404, "not_found"),
        (409, "no_course"),
        (409, "busy"),
        (409, "not_pending"),
        (422, "invalid_input"),
        (400, "invalid_name"),
        (409, "token_mismatch"),
        (409, "ai_values_unconfirmed"),
        (409, "not_open"),
        (422, "invalid_fields"),
    }


def test_contract_points_are_in_the_fixtures(generated: dict[str, Any]) -> None:
    """W3 後の決定が fixture に表れている。"""
    visits = generated["doctor_visits"]["body"]["visits"]
    assert {v["status"] for v in visits} == {"generating", "ready", "failed"}
    assert all(isinstance(v["reception_no"], str) for v in visits)
    assert generated["doctor_skills_invalid"]["body"]["invalid"]
    assert generated["doctor_skills"]["body"]["invalid"] == []
    assert generated["doctor_skill_change_approve"]["body"]["new_version"] == 2
    assert generated["doctor_skill_change_reject"]["body"] == {"ok": True}
    assert generated["doctor_unprocessed"]["body"]["entries"]


def test_does_not_touch_real_skills(
    script: ModuleType, tmp_path: Path, generated: dict[str, Any]
) -> None:
    before = {p: p.read_bytes() for p in SKILLS_DIR.rglob("SKILL.md")}
    script.build_fixtures(tmp_path)
    assert {p: p.read_bytes() for p in SKILLS_DIR.rglob("SKILL.md")} == before


def test_write_fixtures(script: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "out"
    stale = out / "old.json"
    out.mkdir()
    stale.write_text("{}", "utf-8")
    data = {"a_b": {"method": "GET", "path": "/api/x", "request": None}}
    written = script.write_fixtures(data, out)
    assert [p.name for p in written] == ["a_b.json"]
    assert not stale.exists()  # 消えた経路の古い fixture を残さない
    assert json.loads((out / "a_b.json").read_text("utf-8")) == data["a_b"]


# ---------------------------------------------------------------------------
# 印刷の経路（text/html。JSON の fixture とは別枠で検査する）
# ---------------------------------------------------------------------------

REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
HTML = '<!DOCTYPE html>\n<html lang="ja"><body>（合成）</body></html>'


def _html_response(status: int = 200, **headers: str) -> httpx.Response:
    base = {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
        "content-security-policy": REPORT_CSP,
    }
    merged = {k: v for k, v in {**base, **headers}.items() if v != ""}
    return httpx.Response(status, headers=merged, text=HTML)


def test_report_route_is_in_the_app(script: ModuleType, tmp_path: Path) -> None:
    """レポートの経路はアプリに載っている（JSON の経路から除くだけで、消えたら落ちる）。"""
    from api_helpers import make_app

    routes = script.app_routes(make_app(tmp_path))
    assert script.REPORT_HTML_ROUTE in routes
    assert routes - {script.REPORT_HTML_ROUTE} == script.JSON_ROUTES


def test_report_checks_cover_success_and_failures(dump: Any) -> None:
    checks = dump.report_checks
    assert set(checks) == {
        "ready",
        "not_logged_in",
        "not_found",
        "generating",
        "printed",
    }
    ready = checks["ready"]
    assert ready["status"] == 200
    assert ready["content_type"].startswith("text/html")
    assert ready["cache_control"] == "no-store"
    assert ready["content_security_policy"] == REPORT_CSP
    assert ready["doctype"] is True
    assert checks["not_logged_in"] == {"status": 401, "error": "not_logged_in"}
    for name in ("not_found", "generating", "printed"):
        assert checks[name] == {"status": 404, "error": "not_found"}, name


def test_report_checks_are_deterministic(
    script: ModuleType, dump: Any, tmp_path_factory: pytest.TempPathFactory
) -> None:
    again = script.build_dump(tmp_path_factory.mktemp("dump-report"))
    assert again.report_checks == dump.report_checks


def test_check_report_html_accepts_the_contract(script: ModuleType) -> None:
    summary = script.check_report_html("ready", _html_response())
    assert summary["status"] == 200
    assert summary["doctype"] is True


@pytest.mark.parametrize(
    ("label", "response"),
    [
        ("500", _html_response(500)),
        ("JSON", _html_response(**{"content-type": "application/json"})),
        ("no-store が無い", _html_response(**{"cache-control": ""})),
        ("キャッシュ可", _html_response(**{"cache-control": "max-age=60"})),
        ("CSP が無い", _html_response(**{"content-security-policy": ""})),
        (
            "CSP が緩い",
            _html_response(**{"content-security-policy": "default-src *"}),
        ),
    ],
)
def test_check_report_html_rejects_broken_responses(
    script: ModuleType, label: str, response: httpx.Response
) -> None:
    with pytest.raises(script.DumpError):
        script.check_report_html(label, response)


def test_check_report_html_rejects_a_non_html_body(script: ModuleType) -> None:
    response = httpx.Response(
        200,
        headers={
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "content-security-policy": REPORT_CSP,
        },
        text='{"ok": true}',
    )
    with pytest.raises(script.DumpError):
        script.check_report_html("not html", response)


@pytest.mark.parametrize(
    ("response", "status", "code"),
    [
        (httpx.Response(200, json={"error": "not_found"}), 404, "not_found"),
        (httpx.Response(404, json={"error": "other"}), 404, "not_found"),
        (httpx.Response(404, text="<html>404</html>"), 404, "not_found"),
        (httpx.Response(500, json={"error": "internal_error"}), 401, "not_logged_in"),
    ],
)
def test_check_report_error_rejects_unexpected(
    script: ModuleType, response: httpx.Response, status: int, code: str
) -> None:
    with pytest.raises(script.DumpError):
        script.check_report_error("x", response, status, code)

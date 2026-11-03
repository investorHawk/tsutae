"""患者 API（docs/architecture.md §8 患者・§8b）と deps の Cookie。"""

from __future__ import annotations

import ast
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from api_helpers import (
    add_entry,
    add_patient,
    api_client,
    db_conn,
    register,
    set_patient_cookie,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.api import deps
from tsutae.config import PACKAGE_ROOT, PATIENT_STRINGS_PATH, jst_datetime
from tsutae.schemas import ClosedAnswer, EntryCreate

C1 = [(1, date(2026, 10, 27))]
SENTINEL = "磯鷲架空太郎のひみつの文"


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    patient_id = add_patient(client.app, courses=C1)
    assert register(client, patient_id).status_code == 200
    return patient_id


def _fever(t: float) -> dict:
    return {
        "answers": [{"question_key": "fever", "value": "measured", "temperature": t}]
    }


# ---------------------------------------------------------------------------
# 登録と Cookie
# ---------------------------------------------------------------------------


def test_register_unknown_patient_is_404(client: TestClient) -> None:
    for bad in ("P-ZZZZZZZZ", "garbage", "", "p-demo0001"):
        r = client.post("/api/patient/register", json={"pid": bad})
        assert r.status_code == 404
        assert r.json() == {"error": "unknown_patient"}
    assert deps.PATIENT_COOKIE not in client.cookies


def test_register_sets_httponly_lax_cookie(client: TestClient) -> None:
    patient_id = add_patient(client.app)
    r = register(client, patient_id)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    header = r.headers["set-cookie"]
    assert header.startswith(f"{deps.PATIENT_COOKIE}={patient_id}.")  # 署名つき
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert "secure" not in header.lower()  # http の開発環境では付けない
    secret = client.app.state.settings.secret_key
    cookie = client.cookies.get(deps.PATIENT_COOKIE)
    assert deps.verify_patient_token(cookie, secret) == patient_id


def test_register_rejects_bad_body(client: TestClient) -> None:
    for body in ({}, {"pid": 1}, {"pid": "P-AAAAAAAA", "extra": 1}):
        r = client.post("/api/patient/register", json=body)
        assert r.status_code == 422
        assert r.json() == {"error": "invalid_input"}


def test_strings_are_patient_strings_json(client: TestClient) -> None:
    r = client.get("/api/patient/strings")
    assert r.status_code == 200
    assert r.json() == json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))


def test_no_cookie_is_401(client: TestClient) -> None:
    patient_id = add_patient(client.app, courses=C1)
    for method, path in (
        ("get", f"/api/patient/{patient_id}/questions"),
        ("get", f"/api/patient/{patient_id}/entries"),
    ):
        r = getattr(client, method)(path)
        assert r.status_code == 401
        assert r.json() == {"error": "not_logged_in"}
    r = client.post(f"/api/patient/{patient_id}/entries", json={"too_sick": True})
    assert r.status_code == 401


def test_malformed_cookie_is_401(client: TestClient) -> None:
    set_patient_cookie(client, "not-a-pid")
    r = client.get("/api/patient/not-a-pid/questions")
    assert r.status_code == 401
    assert r.json() == {"error": "not_logged_in"}


def test_cookie_and_path_mismatch_is_403(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    for path in (f"/api/patient/{other}/questions", f"/api/patient/{other}/entries"):
        r = client.get(path)
        assert r.status_code == 403
        assert r.json() == {"error": "forbidden"}
    r = client.post(f"/api/patient/{other}/entries", json={"too_sick": True})
    assert r.status_code == 403
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, other) == []


def test_unknown_patient_with_matching_cookie_is_404(client: TestClient) -> None:
    set_patient_cookie(client, "P-ZZZZZZZZ")
    r = client.get("/api/patient/P-ZZZZZZZZ/questions")
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_patient"}


# ---------------------------------------------------------------------------
# 質問集
# ---------------------------------------------------------------------------


def test_questions_folfox(client: TestClient, pid: str) -> None:
    r = client.get(f"/api/patient/{pid}/questions")
    assert r.status_code == 200
    body = r.json()
    assert body["skill_version"] == "regimen-folfox@1"
    keys = [q["key"] for q in body["questions"]]
    assert keys == ["numbness", "diarrhea", "stomatitis", "nausea_appetite", "fever"]
    assert set(body["questions"][0]) == {"key", "text", "answer_type"}


def test_questions_capox(client: TestClient) -> None:
    patient_id = add_patient(client.app, "CAPOX", courses=C1)
    register(client, patient_id)
    body = client.get(f"/api/patient/{patient_id}/questions").json()
    assert body["skill_version"].startswith("regimen-capox@")
    assert "hand_foot" in [q["key"] for q in body["questions"]]


# ---------------------------------------------------------------------------
# 記録の保存
# ---------------------------------------------------------------------------


def test_post_entry_saves_with_current_skill_version(
    client: TestClient, pid: str
) -> None:
    body = {
        "by_proxy": True,
        "answers": [{"question_key": "diarrhea", "value": "present"}],
        "free_text": "  朝から少しおなかがゆるい  ",
    }
    r = client.post(f"/api/patient/{pid}/entries", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["notices"] == []
    with db_conn(client.app) as conn:
        saved = db.get_entry(conn, out["entry_id"])
    assert saved is not None
    assert saved.patient_id == pid
    assert saved.skill_version == "regimen-folfox@1"
    assert saved.kind == "mixed"
    assert saved.by_proxy is True
    assert saved.free_text == "朝から少しおなかがゆるい"
    assert saved.record_date == date(2026, 11, 9)


def test_post_entry_38_0_gives_fever_notice(client: TestClient, pid: str) -> None:
    r = client.post(f"/api/patient/{pid}/entries", json=_fever(38.0))
    assert r.status_code == 200
    assert r.json()["notices"] == ["fixed_rule.fever_38"]


def test_post_entry_37_9_gives_no_notice(client: TestClient, pid: str) -> None:
    r = client.post(f"/api/patient/{pid}/entries", json=_fever(37.9))
    assert r.status_code == 200
    assert r.json()["notices"] == []


def test_post_too_sick(client: TestClient, pid: str) -> None:
    r = client.post(f"/api/patient/{pid}/entries", json={"too_sick": True})
    assert r.status_code == 200
    with db_conn(client.app) as conn:
        assert db.get_entry(conn, r.json()["entry_id"]).kind == "too_sick"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"free_text": "   "},
        {"too_sick": True, "free_text": SENTINEL},
        {"free_text": SENTINEL * 200},
        {"free_text": SENTINEL, "unexpected": 1},
        {"free_text": SENTINEL, "answers": [{"question_key": "fever"}]},
        {"answers": [{"question_key": "fever", "value": "measured"}]},
        {
            "answers": [
                {"question_key": "fever", "value": "measured", "temperature": 50}
            ]
        },
        {"answers": [{"question_key": "diarrhea", "value": "none", "temperature": 37}]},
        {
            "answers": [
                {"question_key": "diarrhea", "value": "none"},
                {"question_key": "diarrhea", "value": "hard"},
            ]
        },
        # Skill に照らした検査
        {"answers": [{"question_key": "hand_foot", "value": "present"}]},
        {
            "answers": [{"question_key": "fever", "value": "hard"}],
            "free_text": SENTINEL,
        },
        {"answers": [{"question_key": "numbness", "value": "not_measured"}]},
        {
            "answers": [
                {"question_key": "numbness", "value": "measured", "temperature": 37.0}
            ]
        },
    ],
)
def test_invalid_entry_is_422_without_echo(
    client: TestClient, pid: str, body: dict
) -> None:
    r = client.post(f"/api/patient/{pid}/entries", json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}
    assert SENTINEL not in r.text
    with db_conn(client.app) as conn:
        assert db.list_entries(conn, pid) == []


def test_malformed_json_is_422(client: TestClient, pid: str) -> None:
    r = client.post(
        f"/api/patient/{pid}/entries",
        content=b'{"free_text": "' + SENTINEL.encode() + b'"',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}
    assert SENTINEL not in r.text


# ---------------------------------------------------------------------------
# 記録の一覧
# ---------------------------------------------------------------------------


def test_get_entries_with_question_text(client: TestClient, pid: str) -> None:
    client.post(
        f"/api/patient/{pid}/entries",
        json={
            "answers": [
                {"question_key": "diarrhea", "value": "hard"},
                {"question_key": "fever", "value": "not_measured"},
            ],
            "free_text": "下痢が続いた",
        },
    )
    client.post(f"/api/patient/{pid}/entries", json={"too_sick": True})
    r = client.get(f"/api/patient/{pid}/entries")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 2
    first = entries[0]
    assert set(first) == {
        "id",
        "recorded_at",
        "record_date",
        "kind",
        "by_proxy",
        "skill_version",
        "answers",
        "free_text",
    }
    assert first["kind"] == "mixed"
    assert first["record_date"] == "2026-11-09"
    assert first["recorded_at"].endswith("+09:00")
    assert first["skill_version"] == "regimen-folfox@1"
    assert first["free_text"] == "下痢が続いた"
    by_key = {a["question_key"]: a for a in first["answers"]}
    assert by_key["diarrhea"] == {
        "question_key": "diarrhea",
        "value": "hard",
        "temperature": None,
        "question_text": "下痢はありましたか",
    }
    assert by_key["fever"]["question_text"] == "熱を測りましたか"
    assert entries[1]["kind"] == "too_sick"
    assert entries[1]["answers"] == []
    assert entries[1]["free_text"] is None


def test_get_entries_unknown_version_gives_null_text(
    client: TestClient, pid: str
) -> None:
    entry = EntryCreate(
        answers=[ClosedAnswer(question_key="numbness", value="present")]
    )
    add_entry(client.app, pid, entry, skill_version="regimen-folfox@99")
    add_entry(client.app, pid, entry, skill_version="report-format-default@1")
    entries = client.get(f"/api/patient/{pid}/entries").json()["entries"]
    assert [e["answers"][0]["question_text"] for e in entries] == [None, None]
    assert entries[0]["skill_version"] == "regimen-folfox@99"


def test_get_entries_only_own(client: TestClient, pid: str) -> None:
    other = add_patient(client.app, courses=C1)
    add_entry(client.app, other, EntryCreate(free_text="ほかの人の記録"))
    client.post(f"/api/patient/{pid}/entries", json={"free_text": "自分の記録"})
    entries = client.get(f"/api/patient/{pid}/entries").json()["entries"]
    assert [e["free_text"] for e in entries] == ["自分の記録"]


# ---------------------------------------------------------------------------
# 共通のエラーの形
# ---------------------------------------------------------------------------


def test_unknown_route_and_method_use_error_shape(client: TestClient) -> None:
    r = client.get("/api/no-such-route")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}
    r = client.delete("/api/patient/strings")
    assert r.status_code == 405
    assert r.json() == {"error": "method_not_allowed"}


def test_unhandled_exception_is_500_without_text(tmp_path: Path) -> None:
    from api_helpers import make_app

    app = make_app(tmp_path)

    @app.get("/api/boom")
    def boom() -> dict:
        raise RuntimeError(SENTINEL)

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/boom")
    assert r.status_code == 500
    assert r.json() == {"error": "internal_error"}
    assert SENTINEL not in r.text


def test_unhandled_exception_logs_type_and_id_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from api_helpers import make_app

    app = make_app(tmp_path)

    @app.post("/api/boom")
    def boom(body: dict) -> dict:
        raise KeyError(SENTINEL + str(body))

    with (
        caplog.at_level(logging.DEBUG, logger="tsutae.api.deps"),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        r = c.post("/api/boom", json={"text": SENTINEL})
    assert r.status_code == 500
    assert r.json() == {"error": "internal_error"}
    records = [x for x in caplog.records if x.name == "tsutae.api.deps"]
    assert len(records) == 1
    (record,) = records
    assert record.levelno == logging.ERROR
    assert record.exc_info is None  # traceback（例外の文面を含む）を残さない
    message = record.getMessage()
    assert deps.INTERNAL_ERROR_EVENT in message
    assert "error_type=KeyError" in message
    error_id = r.headers[deps.ERROR_ID_HEADER]
    assert re.fullmatch(r"[0-9a-f]{32}", error_id)
    assert f"error_id={error_id}" in message
    assert SENTINEL not in caplog.text
    assert SENTINEL not in r.text


def test_internal_error_ids_differ_per_request(tmp_path: Path) -> None:
    from api_helpers import make_app

    app = make_app(tmp_path)

    @app.get("/api/boom")
    def boom() -> dict:
        raise RuntimeError(SENTINEL)

    with TestClient(app, raise_server_exceptions=False) as c:
        ids = {c.get("/api/boom").headers[deps.ERROR_ID_HEADER] for _ in range(3)}
    assert len(ids) == 3


# ---------------------------------------------------------------------------
# アーキテクチャ: 患者 API は変換結果・パイプラインに触れない
# ---------------------------------------------------------------------------

FORBIDDEN_MODULES = ("tsutae.pipeline", "tsutae.report")
FORBIDDEN_NAMES = {"get_timeline", "get_report"}


def _imports(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return modules, names


@pytest.mark.parametrize("name", ["patient.py", "deps.py", "fixed_rules.py"])
def test_patient_api_does_not_import_pipeline_or_report(name: str) -> None:
    modules, names = _imports(PACKAGE_ROOT / "api" / name)
    for module in modules:
        assert not module.startswith(FORBIDDEN_MODULES), module
    assert not (names & FORBIDDEN_NAMES)
    assert not (names & {"pipeline", "report"})


# ---------------------------------------------------------------------------
# deps: 医師の Cookie（HMAC-SHA256、12時間）
# ---------------------------------------------------------------------------

SECRET = "unit-secret"
T0 = jst_datetime(date(2026, 11, 9), 9, 0)


def test_doctor_token_round_trip() -> None:
    token = deps.make_doctor_token(SECRET, T0)
    assert deps.verify_doctor_token(token, SECRET, T0)
    assert deps.verify_doctor_token(token, SECRET, T0 + timedelta(hours=11, minutes=59))


def test_doctor_token_expires_after_12_hours() -> None:
    token = deps.make_doctor_token(SECRET, T0)
    assert not deps.verify_doctor_token(
        token, SECRET, T0 + timedelta(hours=12, seconds=1)
    )


def test_doctor_token_rejects_tampering() -> None:
    token = deps.make_doctor_token(SECRET, T0)
    issued, sig = token.split(".")
    later = str(int(issued) + 3600)
    for bad in (
        None,
        "",
        "garbage",
        f"{later}.{sig}",
        f"{issued}.{sig[:-1]}0" if sig[-1] != "0" else f"{issued}.{sig[:-1]}1",
        f"{issued}.",
        f".{sig}",
        f"x{issued}.{sig}",
        token + ".extra",
    ):
        assert not deps.verify_doctor_token(bad, SECRET, T0), bad
    assert not deps.verify_doctor_token(token, "other-secret", T0)


def test_doctor_token_rejects_future_issue() -> None:
    token = deps.make_doctor_token(SECRET, T0 + timedelta(minutes=10))
    assert not deps.verify_doctor_token(token, SECRET, T0)


def test_check_doctor_password(tmp_path: Path) -> None:
    from api_helpers import TEST_PASSWORD, make_settings

    settings = make_settings(tmp_path)
    assert deps.check_doctor_password(TEST_PASSWORD, settings)
    assert not deps.check_doctor_password(TEST_PASSWORD + "x", settings)
    assert not deps.check_doctor_password("", settings)


def _doctor_app(tmp_path: Path) -> FastAPI:
    from api_helpers import make_settings

    app = FastAPI()
    app.state.settings = make_settings(tmp_path)
    deps.install_error_handlers(app)

    @app.get("/only-doctor", dependencies=[Depends(deps.require_doctor)])
    def only_doctor() -> dict:
        return {"ok": True}

    @app.post("/login")
    def login() -> dict:
        from fastapi.responses import JSONResponse

        response = JSONResponse({"ok": True})
        deps.set_doctor_cookie(response, app.state.settings)
        return response

    @app.post("/logout")
    def logout() -> dict:
        from fastapi.responses import JSONResponse

        response = JSONResponse({"ok": True})
        deps.clear_doctor_cookie(response)
        return response

    return app


def test_require_doctor(tmp_path: Path, fixed_today: str) -> None:
    with TestClient(_doctor_app(tmp_path)) as c:
        r = c.get("/only-doctor")
        assert r.status_code == 401
        assert r.json() == {"error": "not_logged_in"}
        login = c.post("/login")
        header = login.headers["set-cookie"]
        assert header.startswith(f"{deps.DOCTOR_COOKIE}=")
        assert "HttpOnly" in header and "samesite=lax" in header.lower()
        assert c.get("/only-doctor").json() == {"ok": True}
        c.post("/logout")
        assert c.get("/only-doctor").status_code == 401


def test_require_doctor_rejects_expired_cookie(
    tmp_path: Path, fixed_today: str
) -> None:
    with TestClient(_doctor_app(tmp_path)) as c:
        old = deps.make_doctor_token(
            c.app.state.settings.secret_key, jst_datetime(date(2026, 11, 7), 9)
        )
        c.cookies.set(deps.DOCTOR_COOKIE, old)
        assert c.get("/only-doctor").status_code == 401


# ---------------------------------------------------------------------------
# 医師 API の全経路が認証を要すること（login・logout を除く）
# ---------------------------------------------------------------------------

DOCTOR_PREFIX = "/api/doctor/"
DOCTOR_PUBLIC = {"/api/doctor/login", "/api/doctor/logout"}
_PATH_PARAM = re.compile(r"\{([^}:]+)(?::[^}]*)?\}")


def _doctor_routes(app: FastAPI) -> list[tuple[str, str]]:
    """create_app() に載った /api/doctor/* の (メソッド, 経路)。login・logout を除く。

    FastAPI 0.162 は include_router した経路を遅延で展開する（`app.routes` には
    `_IncludedRouter` しか無い）ので、公開の `iter_route_contexts` で開く。
    """
    from fastapi.routing import iter_route_contexts

    found: set[tuple[str, str]] = set()
    for route in iter_route_contexts(app.routes):
        path = route.path_format or route.path
        if not path or not path.startswith(DOCTOR_PREFIX) or path in DOCTOR_PUBLIC:
            continue
        found.update((m, path) for m in (route.methods or set()) - {"HEAD"})
    return sorted(found)


def _fill_path(path: str) -> str:
    return _PATH_PARAM.sub(
        lambda m: "P-ZZZZZZZZ" if m[1] in ("pid", "patient_id") else "1", path
    )


def _bad_doctor_cookies(secret: str) -> dict[str, str | None]:
    expired = deps.make_doctor_token(secret, jst_datetime(date(2026, 11, 7), 9))
    forged = deps.make_doctor_token(
        "not-the-secret", jst_datetime(date(2026, 11, 9), 8)
    )
    return {"missing": None, "garbage": "garbage", "forged": forged, "expired": expired}


def _routes_without_auth(app: FastAPI) -> list[str]:
    """Cookie が無い・壊れている・失効のどれかで 401 not_logged_in にならない経路。"""
    bad: list[str] = []
    with TestClient(app, raise_server_exceptions=False) as c:
        for label, value in _bad_doctor_cookies(app.state.settings.secret_key).items():
            for method, path in _doctor_routes(app):
                c.cookies.clear()
                if value is not None:
                    c.cookies.set(deps.DOCTOR_COOKIE, value)
                r = c.request(method, _fill_path(path))
                if r.status_code != 401 or r.json() != {"error": "not_logged_in"}:
                    bad.append(f"{label} {method} {path} -> {r.status_code}")
    return bad


def test_every_doctor_route_requires_login(tmp_path: Path, fixed_today: str) -> None:
    from api_helpers import make_app

    app = make_app(tmp_path)
    if not _doctor_routes(app):
        pytest.skip("医師 API（tsutae.api.doctor・doctor_skills）がまだ無い")
    assert _routes_without_auth(app) == []


def test_doctor_route_check_finds_unprotected_route(
    tmp_path: Path, fixed_today: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上の検査が空振りしないこと（認証の無い経路を見つける）。"""
    import sys

    from api_helpers import make_app

    from tsutae.api import app as app_module

    pkg = tmp_path / "tsutae_fake_doctor_router"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "from fastapi import APIRouter, Depends\n"
        "from tsutae.api.deps import require_doctor\n"
        "router = APIRouter()\n"
        "@router.post('/api/doctor/login')\n"
        "def login():\n    return {'ok': True}\n"
        "@router.get('/api/doctor/patients', dependencies=[Depends(require_doctor)])\n"
        "def patients():\n    return {'patients': []}\n"
        "@router.post('/api/doctor/visits/{visit_id}/printed')\n"
        "def printed(visit_id: int):\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(app_module, "OPTIONAL_ROUTERS", ("tsutae_fake_doctor_router",))
    try:
        app = make_app(tmp_path)
        assert _doctor_routes(app) == [
            ("GET", "/api/doctor/patients"),
            ("POST", "/api/doctor/visits/{visit_id}/printed"),
        ]
        bad = _routes_without_auth(app)
    finally:
        sys.modules.pop("tsutae_fake_doctor_router", None)
    assert len(bad) == 4
    assert all("/api/doctor/visits/{visit_id}/printed -> 200" in b for b in bad)

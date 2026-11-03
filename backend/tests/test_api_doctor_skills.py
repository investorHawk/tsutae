"""医師 API: Skill の一覧と書き換え（D4。docs/architecture.md §8・§8b・§9b）。

skills_home は tmp_path に backend/skills_home を写して使う（本物を書き換えない）。
editor は api_helpers.FakeEditor（作業コピーの SKILL.md に transform を掛ける）。
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from api_helpers import FakeEditor, api_client, db_conn, login_doctor
from fastapi.testclient import TestClient

from tsutae import db
from tsutae.config import SKILLS_HOME
from tsutae.skillchange import lock as lock_module
from tsutae.skillchange import service as service_module
from tsutae.skillchange.lock import skill_lock
from tsutae.skills import load_skill

NAME = "regimen-folfox"
OLD_Q = "text: 下痢はありましたか"
NEW_Q = "text: 下痢やお腹のゆるさはありましたか"
REQUEST = "下痢の質問をお腹のゆるさも含む文にして"
CHANGE_KEYS = {
    "id",
    "skill_name",
    "requested_text",
    "diff",
    "status",
    "base_version",
    "new_version",
    "error_code",
    "created_at",
    "decided_at",
}


def _change_question(text: str) -> str:
    assert OLD_Q in text
    return text.replace(OLD_Q, NEW_Q)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    dst = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, dst)
    return dst


def _client(tmp_path: Path, home: Path, transform: Callable[[str], str] | None):
    editor = FakeEditor(transform=transform)
    return api_client(tmp_path, editor=editor, skills_dir=home / ".claude" / "skills")


@pytest.fixture
def client(tmp_path: Path, home: Path, fixed_today: str):
    with _client(tmp_path, home, _change_question) as c:
        login_doctor(c)
        yield c


def _skill_file(home: Path, name: str = NAME) -> Path:
    return home / ".claude" / "skills" / name / "SKILL.md"


def _request(client: TestClient, **body: Any) -> Any:
    payload = {"skill_name": NAME, "request_text": REQUEST, **body}
    return client.post("/api/doctor/skill-changes", json=payload)


# ---------------------------------------------------------------------------
# 一覧
# ---------------------------------------------------------------------------


def test_list_skills(client: TestClient) -> None:
    r = client.get("/api/doctor/skills")
    assert r.status_code == 200
    assert r.json() == {
        "skills": [
            {"name": "regimen-capox", "version": 1},
            {"name": "regimen-folfox", "version": 1},
            {"name": "report-format-default", "version": 1},
        ],
        "invalid": [],
    }


def test_list_skills_skips_non_skill_dirs(client: TestClient, home: Path) -> None:
    skills = home / ".claude" / "skills"
    (skills / "Not_A_Skill").mkdir()
    (skills / "regimen-empty").mkdir()  # SKILL.md が無い
    (skills / "notes.txt").write_text("x", encoding="utf-8")
    body = client.get("/api/doctor/skills").json()
    names = [s["name"] for s in body["skills"]]
    assert names == ["regimen-capox", "regimen-folfox", "report-format-default"]
    assert body["invalid"] == []  # SKILL.md の無い任意のディレクトリは Skill でない


# ---------------------------------------------------------------------------
# 依頼 → 承認
# ---------------------------------------------------------------------------


def test_request_then_approve(client: TestClient, home: Path) -> None:
    before = _skill_file(home).read_text("utf-8")
    r = _request(client)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "status", "diff"}
    assert body["status"] == "pending"
    assert NEW_Q in body["diff"] and OLD_Q in body["diff"]
    assert _skill_file(home).read_text("utf-8") == before  # 本体はまだ変えない
    editor = client.app.state.skill_editor
    assert [(name, text) for _root, name, text in editor.calls] == [(NAME, REQUEST)]

    (item,) = client.get("/api/doctor/skill-changes").json()["skill_changes"]
    assert set(item) == CHANGE_KEYS
    assert item["id"] == body["id"]
    assert item["status"] == "pending"
    assert item["requested_text"] == REQUEST
    assert item["base_version"] == 1
    assert item["new_version"] is None

    r = client.post(f"/api/doctor/skill-changes/{body['id']}/approve")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "new_version": 2}
    after = load_skill(NAME, home / ".claude" / "skills")
    assert after.version == 2
    assert NEW_Q in _skill_file(home).read_text("utf-8")
    with db_conn(client.app) as conn:
        assert db.latest_skill_version(conn, NAME)["version"] == 2
    (item,) = client.get("/api/doctor/skill-changes").json()["skill_changes"]
    assert item["status"] == "approved"
    assert item["new_version"] == 2
    assert item["decided_at"].endswith("+09:00")
    versions = client.get("/api/doctor/skills").json()["skills"]
    assert {"name": NAME, "version": 2} in versions


def test_approve_twice_is_409(client: TestClient) -> None:
    cid = _request(client).json()["id"]
    assert client.post(f"/api/doctor/skill-changes/{cid}/approve").status_code == 200
    r = client.post(f"/api/doctor/skill-changes/{cid}/approve")
    assert r.status_code == 409
    assert r.json() == {"error": "not_pending"}


def test_reject(client: TestClient, home: Path) -> None:
    before = _skill_file(home).read_text("utf-8")
    cid = _request(client).json()["id"]
    r = client.post(f"/api/doctor/skill-changes/{cid}/reject")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert _skill_file(home).read_text("utf-8") == before
    (item,) = client.get("/api/doctor/skill-changes").json()["skill_changes"]
    assert item["status"] == "rejected"
    for action in ("approve", "reject"):
        r = client.post(f"/api/doctor/skill-changes/{cid}/{action}")
        assert r.status_code == 409
        assert r.json() == {"error": "not_pending"}


def test_stale_approve_is_409(client: TestClient) -> None:
    first = _request(client).json()["id"]
    second = _request(client).json()["id"]
    assert client.post(f"/api/doctor/skill-changes/{first}/approve").status_code == 200
    r = client.post(f"/api/doctor/skill-changes/{second}/approve")
    assert r.status_code == 409
    assert r.json() == {"error": "stale"}
    statuses = [
        c["status"]
        for c in client.get("/api/doctor/skill-changes").json()["skill_changes"]
    ]
    assert statuses == ["approved", "failed"]


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_decide_unknown_change_is_404(client: TestClient, action: str) -> None:
    r = client.post(f"/api/doctor/skill-changes/999/{action}")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize("cid", ["abc", "0", "9" * 30])
def test_decide_bad_id_is_422(client: TestClient, action: str, cid: str) -> None:
    r = client.post(f"/api/doctor/skill-changes/{cid}/{action}")
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


# ---------------------------------------------------------------------------
# 依頼の失敗
# ---------------------------------------------------------------------------


def test_no_change_is_failed_and_cannot_be_approved(
    tmp_path: Path, home: Path, fixed_today: str
) -> None:
    with _client(tmp_path, home, lambda text: text) as c:
        login_doctor(c)
        r = _request(c)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"
        assert body["diff"] is None
        (item,) = c.get("/api/doctor/skill-changes").json()["skill_changes"]
        assert item["error_code"] == "no_change"
        r = c.post(f"/api/doctor/skill-changes/{body['id']}/approve")
        assert r.status_code == 409
        assert r.json() == {"error": "not_pending"}


def test_request_with_identifier_is_failed_without_editor(client: TestClient) -> None:
    r = _request(client, request_text="田中さんの記録に合わせて下痢の質問を直して")
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert client.app.state.skill_editor.calls == []
    (item,) = client.get("/api/doctor/skill-changes").json()["skill_changes"]
    assert item["error_code"] == "h1_blocked"


@pytest.mark.parametrize(
    "body, status, code",
    [
        ({"skill_name": "../etc"}, 400, "invalid_name"),
        ({"skill_name": "Regimen-Folfox"}, 400, "invalid_name"),
        ({"request_text": "   "}, 400, "invalid_request"),
        ({"request_text": "あ" * 2001}, 400, "invalid_request"),
        ({"skill_name": "regimen-nothing"}, 404, "unknown_skill"),
    ],
)
def test_request_rejected_before_row(
    client: TestClient, body: dict, status: int, code: str
) -> None:
    r = _request(client, **body)
    assert r.status_code == status
    assert r.json() == {"error": code}
    assert client.get("/api/doctor/skill-changes").json() == {"skill_changes": []}
    assert client.app.state.skill_editor.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"skill_name": NAME},
        {"request_text": REQUEST},
        {"skill_name": NAME, "request_text": 1},
        {"skill_name": NAME, "request_text": REQUEST, "extra": 1},
    ],
)
def test_request_invalid_body_is_422(client: TestClient, body: dict) -> None:
    r = client.post("/api/doctor/skill-changes", json=body)
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


def test_request_without_editor_is_503(
    tmp_path: Path, home: Path, fixed_today: str
) -> None:
    with _client(tmp_path, home, _change_question) as c:
        login_doctor(c)
        c.app.state.skill_editor = None
        r = _request(c)
        assert r.status_code == 503
        assert r.json() == {"error": "editor_unavailable"}
        assert c.get("/api/doctor/skill-changes").json() == {"skill_changes": []}


def test_list_changes_empty(client: TestClient) -> None:
    assert client.get("/api/doctor/skill-changes").json() == {"skill_changes": []}


# ---------------------------------------------------------------------------
# 一覧: 壊れた Skill を黙って落とさない（Codex レビュー 4）
# ---------------------------------------------------------------------------


def _break(home: Path, name: str) -> None:
    _skill_file(home, name).write_text("frontmatter が無い本文だけ\n", "utf-8")


def test_list_skills_reports_broken_required_skill(
    client: TestClient, home: Path
) -> None:
    _break(home, NAME)
    r = client.get("/api/doctor/skills")
    assert r.status_code == 200  # 印刷待ち等の画面を止めない（ログイン確認もこの経路）
    body = r.json()
    assert body["skills"] == [
        {"name": "regimen-capox", "version": 1},
        {"name": "report-format-default", "version": 1},
    ]
    assert body["invalid"] == [{"name": NAME, "error_code": "format", "required": True}]


def test_list_skills_reports_missing_required_skill(
    client: TestClient, home: Path
) -> None:
    shutil.rmtree(home / ".claude" / "skills" / "report-format-default")
    body = client.get("/api/doctor/skills").json()
    assert [s["name"] for s in body["skills"]] == ["regimen-capox", "regimen-folfox"]
    assert body["invalid"] == [
        {"name": "report-format-default", "error_code": "missing", "required": True}
    ]


def test_list_skills_reports_broken_optional_skill(
    client: TestClient, home: Path
) -> None:
    extra = home / ".claude" / "skills" / "regimen-extra"
    extra.mkdir()
    (extra / "SKILL.md").write_text("---\nname: regimen-extra\n---\n本文\n", "utf-8")
    body = client.get("/api/doctor/skills").json()
    assert len(body["skills"]) == 3
    assert body["invalid"] == [
        {"name": "regimen-extra", "error_code": "schema", "required": False}
    ]


# ---------------------------------------------------------------------------
# 承認と却下の排他（Codex レビュー 1）
# ---------------------------------------------------------------------------


def test_reject_waits_for_the_approval_lock(
    client: TestClient, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """承認と同じロックを握られている間の却下は busy（状態を変えない）。"""
    monkeypatch.setattr(lock_module, "LOCK_TIMEOUT_S", 0.2)
    cid = _request(client).json()["id"]
    with skill_lock(_skill_file(home).parent):
        r = client.post(f"/api/doctor/skill-changes/{cid}/reject")
    assert r.status_code == 409
    assert r.json() == {"error": "busy"}
    (item,) = client.get("/api/doctor/skill-changes").json()["skill_changes"]
    assert item["status"] == "pending"


def test_reject_during_approval_does_not_split_skill_and_row(
    client: TestClient, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """承認が本体と skill_versions を書いた直後に却下が来ても、行は approved になる。"""
    cid = _request(client).json()["id"]
    original = db.save_skill_version
    results: dict[str, Any] = {}

    def reject_in_thread() -> None:
        results["reject"] = client.post(f"/api/doctor/skill-changes/{cid}/reject")

    def save_then_race(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        rival = threading.Thread(target=reject_in_thread)
        rival.start()
        rival.join(timeout=0.5)  # ロックが効いていれば却下はまだ終わらない
        results["finished_during_approval"] = not rival.is_alive()
        results["thread"] = rival

    monkeypatch.setattr(db, "save_skill_version", save_then_race)
    approved = client.post(f"/api/doctor/skill-changes/{cid}/approve")
    results["thread"].join(timeout=10)
    assert results["finished_during_approval"] is False
    assert approved.status_code == 200
    assert approved.json() == {"ok": True, "new_version": 2}
    assert results["reject"].status_code == 409
    assert results["reject"].json() == {"error": "not_pending"}
    (item,) = client.get("/api/doctor/skill-changes").json()["skill_changes"]
    assert item["status"] == "approved"
    assert load_skill(NAME, home / ".claude" / "skills").version == 2


# ---------------------------------------------------------------------------
# 依頼の受付後のファイル操作の失敗（Codex レビュー 3。service.py の担当が直す）
# ---------------------------------------------------------------------------


def _raise_os_error(*_args: Any, **_kwargs: Any) -> Any:
    raise OSError("injected")


@pytest.mark.parametrize("where", ["mkdtemp", "mkdir", "open"])
def test_filesystem_failure_after_row_is_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str
) -> None:
    temp_root = tmp_path / "tmp"  # 一時ディレクトリの置き場をこのテスト専用にする
    temp_root.mkdir()
    monkeypatch.setattr(service_module.tempfile, "tempdir", str(temp_root))
    if where == "mkdtemp":
        monkeypatch.setattr(service_module.tempfile, "mkdtemp", _raise_os_error)
    elif where == "mkdir":
        # Path.mkdir は全体で共有（db.connect も呼ぶ）なので、一時ディレクトリの中だけ落とす
        real_mkdir = service_module.Path.mkdir

        def mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
            if service_module._TEMP_PREFIX in str(self):
                raise OSError("injected")
            real_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(service_module.Path, "mkdir", mkdir)
    else:
        monkeypatch.setattr(service_module, "open", _raise_os_error, raising=False)
    r = _request(client)
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    (item,) = client.get("/api/doctor/skill-changes").json()["skill_changes"]
    assert item["status"] == "failed"
    assert isinstance(item["error_code"], str) and 0 < len(item["error_code"]) <= 40
    assert item["error_code"] == service_module.WORKDIR_ERROR
    assert list(temp_root.iterdir()) == []  # 作りかけの一時ディレクトリも消す

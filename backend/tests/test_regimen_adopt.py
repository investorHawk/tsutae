"""下書きの作成・直接編集・確認・採用（サービス層。architecture 9c・spec 9.1）。

完了条件（plan §3 T93）:
- 採用後 load_regimen_skill で読める（新規は版1、既存は版 N+1）
- token が古い・確かめが無い・患者のいるレジメンで日程を変えた なら止める（409 の code）
- skills_home はテスト用の一時ディレクトリ（本物の backend/skills_home は書き換えない）
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from regimen_fixtures import extra_form, fill_patch

from tsutae import db
from tsutae.config import SKILLS_HOME, now
from tsutae.db import repo_regimen_drafts as repo
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen import adopt as adopt_module
from tsutae.regimen import load_builtin_form, render_regimen_skill
from tsutae.regimen.adopt import adopt
from tsutae.regimen.drafts import (
    DraftError,
    create_new_draft,
    discard,
    draft_form,
    draft_sources,
    load_draft,
    open_skill_draft,
    patch_draft,
)
from tsutae.regimen.edit import FieldChange, FormPatch
from tsutae.regimen.preview import build_preview
from tsutae.regimen.source import (
    canonical_form_json,
    canonical_sources_json,
    form_from_skill,
    new_draft_form,
)
from tsutae.skillchange.diff import set_version
from tsutae.skills import load_regimen_skill, read_skill_text

TIMEOUT = 90.0


@dataclass
class Env:
    conn: sqlite3.Connection
    home: Path

    @property
    def skills_dir(self) -> Path:
        return self.home / ".claude" / "skills"


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    conn = db.connect(tmp_path / "t.db")
    db.init_db(conn)
    ensure_skill_versions(conn, home / ".claude" / "skills")
    db.seed_question_library(conn)
    yield Env(conn, home)
    conn.close()


def _patch(env: Env, draft_id: int, patch: FormPatch) -> dict:
    return patch_draft(
        env.conn, draft_id, patch, skills_dir=env.skills_dir, timeout_s=TIMEOUT
    )


def _filled_new(env: Env, name: str = "folfiri_bv") -> dict:
    draft = create_new_draft(env.conn)
    return _patch(env, draft["id"], fill_patch(draft_form(draft), extra_form(name)))


def _preview(env: Env, draft_id: int) -> dict:
    draft = load_draft(env.conn, draft_id, timeout_s=TIMEOUT)
    return build_preview(env.conn, draft, skills_dir=env.skills_dir)


def _adopt(env: Env, draft_id: int, token: str, confirmed: bool = True):
    return adopt(
        env.conn, draft_id, token, confirmed, skills_home=env.home, timeout_s=TIMEOUT
    )


def _set_sources(env: Env, draft_id: int, sources: dict[str, str]) -> None:
    """Claude（T94）が入れた値の出どころを置く（テスト用に repo を直接呼ぶ）。"""
    draft = repo.get_draft(env.conn, draft_id)
    merged = {**draft_sources(draft).root, **sources}
    assert repo.update_draft_form(
        env.conn,
        draft_id,
        form_json=draft["form_json"],
        sources_json=canonical_sources_json(
            draft_sources(draft).model_validate(merged)
        ),
        regimen=draft["regimen"],
    )


def _error(exc: pytest.ExceptionInfo[DraftError]) -> str:
    return exc.value.code


# --- 作る ---------------------------------------------------------------------------


def test_new_draft_has_only_the_fever_question(env: Env) -> None:
    draft = create_new_draft(env.conn)
    form = draft_form(draft)
    assert draft["regimen"] is None and draft["base_version"] is None
    assert [(q.key, q.text, q.answer_type) for q in form.questions] == [
        ("fever", "熱を測りましたか", "temperature")
    ]
    folfox_fever = next(
        q for q in load_builtin_form("regimen-folfox").questions if q.key == "fever"
    )
    assert form.questions[0] == folfox_fever
    assert form.drugs == [] and form.basic.code is None
    assert form == new_draft_form()


def test_existing_draft_starts_from_version_n(env: Env) -> None:
    draft, created = open_skill_draft(
        env.conn, "regimen-folfox", skills_dir=env.skills_dir
    )
    assert created
    assert draft["regimen"] == "FOLFOX" and draft["base_version"] == 1
    assert draft_form(draft) == load_builtin_form("regimen-folfox")
    again, created_again = open_skill_draft(
        env.conn, "regimen-folfox", skills_dir=env.skills_dir
    )
    assert again["id"] == draft["id"] and not created_again


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("report-format-default", "invalid_name"),
        ("../etc", "invalid_name"),
        ("regimen-nope", "unknown_skill"),
    ],
)
def test_existing_draft_rejects_bad_names(env: Env, name: str, code: str) -> None:
    with pytest.raises(DraftError) as exc:
        open_skill_draft(env.conn, name, skills_dir=env.skills_dir)
    assert _error(exc) == code


def test_version_without_form_is_unavailable(env: Env) -> None:
    path = env.skills_dir / "regimen-folfox" / "SKILL.md"
    path.write_text(set_version(path.read_text("utf-8"), 2), "utf-8")  # 旧 D4 の版
    with pytest.raises(DraftError) as exc:
        open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    assert _error(exc) == "form_unavailable"


# --- 直接編集 -------------------------------------------------------------------------


def test_patch_sets_doctor_edit_and_regimen(env: Env) -> None:
    draft = _filled_new(env)
    assert draft["regimen"] == "FOLFIRI-BV"
    assert set(draft_sources(draft).root.values()) == {"doctor_edit"}
    assert draft_form(draft) == extra_form("folfiri_bv")


def test_patch_rejects_and_keeps_the_old_values(env: Env) -> None:
    draft = _filled_new(env)
    bad = FormPatch(changes=(FieldChange("notes", "電話 090-1234-5678"),))
    with pytest.raises(DraftError) as exc:
        _patch(env, draft["id"], bad)
    assert _error(exc) == "invalid_fields"
    assert [(i.field_id, i.code) for i in exc.value.issues] == [("notes", "identifier")]
    assert repo.get_draft(env.conn, draft["id"])["form_json"] == draft["form_json"]


@pytest.mark.parametrize("code", ["FOLFOX", "CAPOX"])
def test_patch_code_of_existing_skill_is_taken(env: Env, code: str) -> None:
    draft = create_new_draft(env.conn)
    with pytest.raises(DraftError) as exc:
        _patch(env, draft["id"], FormPatch(changes=(FieldChange("basic.code", code),)))
    assert [(i.field_id, i.code) for i in exc.value.issues] == [
        ("basic.code", "code_taken")
    ]


def test_patch_code_of_another_open_draft_is_taken(env: Env) -> None:
    _filled_new(env)
    other = create_new_draft(env.conn)
    patch = FormPatch(changes=(FieldChange("basic.code", "FOLFIRI-BV"),))
    with pytest.raises(DraftError) as exc:
        _patch(env, other["id"], patch)
    assert exc.value.issues[0].code == "code_taken"


def test_existing_draft_code_is_locked(env: Env) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-capox", skills_dir=env.skills_dir)
    patch = FormPatch(changes=(FieldChange("basic.code", "CAPOX-X"),))
    with pytest.raises(DraftError) as exc:
        _patch(env, draft["id"], patch)
    assert exc.value.issues[0].code == "code_locked"


# --- working・破棄 --------------------------------------------------------------------


def test_working_blocks_patch_preview_adopt_discard(env: Env) -> None:
    draft = _filled_new(env)
    token = _preview(env, draft["id"])["confirm_token"]
    assert repo.begin_working(env.conn, draft["id"]) == 1
    patch = FormPatch(changes=(FieldChange("notes", "x"),))
    for call in (
        lambda: _patch(env, draft["id"], patch),
        lambda: _adopt(env, draft["id"], token),
        lambda: discard(env.conn, draft["id"], timeout_s=TIMEOUT),
    ):
        with pytest.raises(DraftError) as exc:
            call()
        assert _error(exc) == "working"


def test_stale_working_is_released_on_read(env: Env) -> None:
    draft = _filled_new(env)
    repo.begin_working(env.conn, draft["id"], at=now() - timedelta(seconds=91))
    got = load_draft(env.conn, draft["id"], timeout_s=TIMEOUT)
    assert got["status"] == "open"
    assert got["chat"][-1]["kind"] == "turn_failed"


def test_discard_closes_the_draft(env: Env) -> None:
    draft = _filled_new(env)
    discard(env.conn, draft["id"], timeout_s=TIMEOUT)
    got = repo.get_draft(env.conn, draft["id"])
    assert got["status"] == "discarded" and got["chat"] == []
    with pytest.raises(DraftError) as exc:
        discard(env.conn, draft["id"], timeout_s=TIMEOUT)
    assert _error(exc) == "not_open"
    # 識別名は開いた下書きから外れる
    _filled_new(env)


# --- 確認 ------------------------------------------------------------------------------


def test_preview_of_new_draft(env: Env) -> None:
    draft = _filled_new(env)
    _set_sources(env, draft["id"], {"drugs.d-bv.name": "standard"})
    preview = _preview(env, draft["id"])
    assert preview["issues"] == []
    assert preview["skill_md"] == {
        "kind": "full",
        "text": render_regimen_skill(extra_form("folfiri_bv"), 1),
    }
    assert preview["ai_values"] == [
        {
            "field_id": "drugs.d-bv.name",
            "label": "ベバシズマブ — 薬の名前",
            "value": "ベバシズマブ",
            "source": "standard",
        }
    ]
    assert [q["key"] for q in preview["patient_preview"]] == [
        "diarrhea",
        "nausea_appetite",
        "stomatitis",
        "fatigue",
        "bleeding",
        "fever",
    ]
    assert len(preview["confirm_token"]) == 64
    assert preview["version"] == 1 and preview["skill_name"] == "regimen-folfiri-bv"


def test_preview_of_incomplete_draft_lists_missing(env: Env) -> None:
    draft = create_new_draft(env.conn)
    preview = _preview(env, draft["id"])
    assert preview["skill_md"] is None
    codes = {(i["field_id"], i["code"]) for i in preview["issues"]}
    assert ("basic.code", "required") in codes
    assert ("drugs", "required") in codes


def test_preview_of_existing_draft_is_a_diff(env: Env) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    _patch(env, draft["id"], FormPatch(changes=(FieldChange("notes", "施設の決まり"),)))
    preview = _preview(env, draft["id"])
    diff = preview["skill_md"]["text"]
    assert preview["skill_md"]["kind"] == "diff" and preview["version"] == 2
    assert diff.startswith(
        "--- a/regimen-folfox/SKILL.md\n+++ b/regimen-folfox/SKILL.md"
    )
    assert "-version: 1\n+version: 2\n" in diff
    assert "+施設の決まり\n" in diff


def test_token_changes_with_values(env: Env) -> None:
    draft = _filled_new(env)
    before = _preview(env, draft["id"])["confirm_token"]
    _set_sources(env, draft["id"], {"basic.target": "standard"})
    assert _preview(env, draft["id"])["confirm_token"] != before


# --- 採用（新規）---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "code", "name"),
    [
        ("folfiri_bv", "FOLFIRI-BV", "regimen-folfiri-bv"),
        ("ram_wptx", "RAM-WPTX", "regimen-ram-wptx"),
        ("lonsurf_bv", "LONSURF-BV", "regimen-lonsurf-bv"),
    ],
)
def test_adopt_new_regimen(env: Env, fixture: str, code: str, name: str) -> None:
    draft = _filled_new(env, fixture)
    env.conn.execute(
        "UPDATE regimen_drafts SET chat_json = ? WHERE id = ?",
        ('[{"role": "doctor", "text": "作りたい"}]', draft["id"]),
    )
    env.conn.commit()
    result = _adopt(env, draft["id"], _preview(env, draft["id"])["confirm_token"])
    assert (result.skill_name, result.version, result.regimen) == (name, 1, code)
    skill = load_regimen_skill(code, env.skills_dir)
    assert skill.name == name and skill.version == 1
    text = read_skill_text(name, env.skills_dir)
    assert text == render_regimen_skill(extra_form(fixture), 1)
    saved = db.get_skill_version(env.conn, name, 1)
    assert saved["content"] == text
    assert saved["questions"] == list(skill.questions)
    assert form_from_skill(env.conn, name, 1) == extra_form(fixture)
    got = repo.get_draft(env.conn, draft["id"])
    assert got["status"] == "adopted" and got["adopted_version"] == 1
    assert got["chat"] == []
    library = {q["key"]: q for q in db.list_library_questions(env.conn)}
    assert library["fatigue"]["origin"] == "adopted"
    assert library["bleeding"]["label"] == "出血"
    assert library["diarrhea"]["origin"] == "seed"


def test_adopted_regimen_opens_as_version_2(env: Env) -> None:
    draft = _filled_new(env)
    _adopt(env, draft["id"], _preview(env, draft["id"])["confirm_token"])
    again, created = open_skill_draft(
        env.conn, "regimen-folfiri-bv", skills_dir=env.skills_dir
    )
    assert created and again["base_version"] == 1
    assert draft_form(again) == extra_form("folfiri_bv")
    _patch(env, again["id"], FormPatch(changes=(FieldChange("notes", "追記"),)))
    result = _adopt(env, again["id"], _preview(env, again["id"])["confirm_token"])
    assert result.version == 2
    assert load_regimen_skill("FOLFIRI-BV", env.skills_dir).version == 2


def test_token_mismatch_after_a_change(env: Env) -> None:
    draft = _filled_new(env)
    token = _preview(env, draft["id"])["confirm_token"]
    _patch(env, draft["id"], FormPatch(changes=(FieldChange("notes", "あとから"),)))
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert _error(exc) == "token_mismatch"
    assert not (env.skills_dir / "regimen-folfiri-bv").exists()
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], "0" * 64)
    assert _error(exc) == "token_mismatch"


def test_ai_values_need_confirmation(env: Env) -> None:
    draft = _filled_new(env)
    _set_sources(env, draft["id"], {"side_effects.se-bleeding.phrases": "standard"})
    token = _preview(env, draft["id"])["confirm_token"]
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token, confirmed=False)
    assert _error(exc) == "ai_values_unconfirmed"
    assert _adopt(env, draft["id"], token, confirmed=True).version == 1


def test_incomplete_draft_is_invalid_form(env: Env) -> None:
    draft = create_new_draft(env.conn)
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], _preview(env, draft["id"])["confirm_token"])
    assert _error(exc) == "invalid_form" and exc.value.issues


def test_code_taken_when_the_folder_appears(env: Env) -> None:
    draft = _filled_new(env)
    token = _preview(env, draft["id"])["confirm_token"]
    (env.skills_dir / "regimen-folfiri-bv").mkdir()  # 確かめた後に同じ名前ができた
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert _error(exc) == "code_taken"
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"


def test_code_taken_race_on_mkdir(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    draft = _filled_new(env)
    token = _preview(env, draft["id"])["confirm_token"]
    real_plan = adopt_module._plan

    def plan_then_race(*args, **kwargs):  # 検査の後・mkdir の前に別の採用が作った
        plan = real_plan(*args, **kwargs)
        (env.skills_dir / "regimen-folfiri-bv").mkdir()
        return plan

    monkeypatch.setattr(adopt_module, "_plan", plan_then_race)
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert _error(exc) == "code_taken"


def test_db_failure_removes_the_new_folder(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _filled_new(env)
    token = _preview(env, draft["id"])["confirm_token"]

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(repo, "insert_regimen_form_row", boom)
    with pytest.raises(sqlite3.OperationalError):
        _adopt(env, draft["id"], token)
    assert not (env.skills_dir / "regimen-folfiri-bv").exists()
    assert db.get_skill_version(env.conn, "regimen-folfiri-bv", 1) is None
    assert repo.get_draft(env.conn, draft["id"])["status"] == "open"


# --- 採用（既存）---------------------------------------------------------------------------


def test_adopt_existing_writes_version_n_plus_1(env: Env) -> None:
    before = read_skill_text("regimen-folfox", env.skills_dir)
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    _patch(env, draft["id"], FormPatch(changes=(FieldChange("notes", "施設の決まり"),)))
    result = _adopt(env, draft["id"], _preview(env, draft["id"])["confirm_token"])
    assert result.version == 2
    assert load_regimen_skill("FOLFOX", env.skills_dir).version == 2
    assert db.get_skill_version(env.conn, "regimen-folfox", 1)["content"] == before
    assert db.get_skill_version(env.conn, "regimen-folfox", 2) is not None
    assert form_from_skill(env.conn, "regimen-folfox", 2).notes == "施設の決まり"
    assert form_from_skill(env.conn, "regimen-folfox", 2).prose == (
        load_builtin_form("regimen-folfox").prose
    )


def test_stale_when_the_skill_moved_on(env: Env) -> None:
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    token = _preview(env, draft["id"])["confirm_token"]
    path = env.skills_dir / "regimen-folfox" / "SKILL.md"
    path.write_text(set_version(path.read_text("utf-8"), 2), "utf-8")
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], token)
    assert _error(exc) == "stale"
    assert _preview(env, draft["id"])["issues"][0]["code"] == "stale"


@pytest.mark.parametrize(
    "change",
    [
        FieldChange("basic.cycle_days", 21),
        FieldChange("drugs.d-fu-pump.days", [{"start": 1, "end": 2}]),
        FieldChange(
            "drugs.d-oxaliplatin.days", [{"start": 1, "end": 1}, {"start": 8, "end": 8}]
        ),
    ],
)
def test_schedule_is_locked_when_patients_exist(env: Env, change: FieldChange) -> None:
    db.create_patient(env.conn, "FOLFOX")
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    _patch(env, draft["id"], FormPatch(changes=(change,)))
    preview = _preview(env, draft["id"])
    assert [i["code"] for i in preview["issues"]] == ["schedule_locked"]
    with pytest.raises(DraftError) as exc:
        _adopt(env, draft["id"], preview["confirm_token"])
    assert _error(exc) == "schedule_locked"
    assert load_regimen_skill("FOLFOX", env.skills_dir).version == 1


def test_schedule_can_change_without_patients(env: Env) -> None:
    db.create_patient(env.conn, "CAPOX")  # 別のレジメンの患者
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    _patch(env, draft["id"], FormPatch(changes=(FieldChange("basic.cycle_days", 21),)))
    result = _adopt(env, draft["id"], _preview(env, draft["id"])["confirm_token"])
    assert load_regimen_skill("FOLFOX", env.skills_dir).cycle_days == 21
    assert result.version == 2


def test_drug_name_can_change_with_patients(env: Env) -> None:
    db.create_patient(env.conn, "FOLFOX")
    draft, _ = open_skill_draft(env.conn, "regimen-folfox", skills_dir=env.skills_dir)
    patch = FormPatch(
        changes=(FieldChange("drugs.d-oxaliplatin.name", "エルプラット"),)
    )
    _patch(env, draft["id"], patch)
    assert (
        _adopt(env, draft["id"], _preview(env, draft["id"])["confirm_token"]).version
        == 2
    )


def test_db_failure_restores_the_old_skill(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = read_skill_text("regimen-capox", env.skills_dir)
    draft, _ = open_skill_draft(env.conn, "regimen-capox", skills_dir=env.skills_dir)
    _patch(env, draft["id"], FormPatch(changes=(FieldChange("notes", "x"),)))
    token = _preview(env, draft["id"])["confirm_token"]

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(repo, "mark_adopted_row", boom)
    with pytest.raises(sqlite3.OperationalError):
        _adopt(env, draft["id"], token)
    assert read_skill_text("regimen-capox", env.skills_dir) == before
    assert db.get_skill_version(env.conn, "regimen-capox", 2) is None


def test_canonical_json_is_stable() -> None:
    form = extra_form("ram_wptx")
    assert canonical_form_json(form) == canonical_form_json(
        type(form).model_validate_json(canonical_form_json(form))
    )

"""受診時の生成（docs/architecture.md §7d）。

`generate_visit_report` の手順:
1. 受診を読む。無い・受付番号が消えている（印刷済み・期限切れ）・expires_at を
   過ぎている（purge 前）なら何もしない（Claude を呼ばない）
2. 患者・コース・記録・Skill（今の SKILL.md）・版ごとの質問集（skill_versions）を集め、
   `prepare_input(exclude_literals=(仮名ID, 受付番号))`。受付番号・仮名IDは Claude に
   送らない（自由記載に含む記録は known_identifier で外れる。§7 W2b）
3. `convert`（例外を出さず、失敗は fallback の ConversionResult）。run_start・run_end・
   fallback のログは convert が書く
4. `build_report_data` → `render_report_html`。AI の結果で組み立てられなければ
   AI 変換なし（timeline=None）で組み立て直す（ログ `fallback`、decision は
   `report_error:<型名>`）
5. `db.save_visit_result`（timeline（AI 変換なしなら unprocessed だけの Timeline）・
   report・ready と fallback を1つのトランザクションで。印刷済み・期限切れなら何も
   変えずに VisitClosedError）

- prepare_input までに失敗した（入力が作れない）ときは、フォールバックのレポートも
  作れないので failed。service が run_start・run_end（decision `prepare_error:<型名>`）を書く
- 組み立て直しも失敗したら failed（ログ `visit_failed` を1回、decision は最後の失敗）
- 途中で印刷済みになった受診（`VisitClosedError`）は状態を変えずに終える。ready への
  保存も failed への更新も db の条件付き更新（受付番号が残っている受診だけ）なので、
  別の接続・別プロセスの mark_printed と競合しても printed を戻さない。failed にする
  ときは読み直しも db の書き込みロック（`write_transaction`）の中で行う
- 取り消し（CancelledError）は run_end（decision `cancelled`）を書き、failed にして通す
- ログには文面を入れない（例外は型名だけ）。例外は外へ出さない（取り消しはそのまま通す）
- 保存（save_visit_result）が db の失敗で落ちれば何も残らず、failed にする
  （ログ `visit_failed`、decision は `save_error:<型名>`）
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tsutae import db
from tsutae.config import Settings
from tsutae.config import now as clock_now
from tsutae.db import VisitClosedError, write_transaction
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.logs import EventLogger, PipelineLogger, reason_code
from tsutae.pipeline.orchestrator import convert
from tsutae.pipeline.runner import AgentRunner
from tsutae.report import build_report_data, render_report_html
from tsutae.schemas import (
    ConversionResult,
    Course,
    Entry,
    PreparedInput,
    Question,
    RegimenSkill,
    ReportData,
    ReportFormatSkill,
    RunStats,
    Timeline,
)
from tsutae.skills import (
    REGIMEN_SKILL_NAMES,
    SKILL_FILE_NAME,
    SkillValidationError,
    is_valid_skill_name,
    load_regimen_skill,
    load_report_skill,
    read_skill_text,
    validate_skill_text,
)

__all__ = [
    "MAX_SCANNED_VERSIONS",
    "REPORT_ERROR",
    "ensure_skill_versions",
    "generate_visit_report",
    "questions_by_version",
]

RUN_KIND = "visit"
PREPARE_ERROR = "prepare_error"
REPORT_ERROR = "report_error"
SAVE_ERROR = "save_error"
CANCELLED = "cancelled"
# questions_by_version(conn) が1つの Skill について順に引く版の上限（最新の版は別に必ず引く）
MAX_SCANNED_VERSIONS = 200
_VERSION_RE = re.compile(r"^(?P<name>[a-z0-9-]+)@(?P<version>[1-9][0-9]{0,8})$")
# 読み直し・保存で起こりうる db の例外（NotFoundError は LookupError）
_DB_ERRORS = (sqlite3.Error, ValueError, LookupError)
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _VisitInputs:
    reception_no: str
    patient_id: str
    visit_date: date
    regimen_skill: RegimenSkill
    report_skill: ReportFormatSkill
    courses: tuple[Course, ...]
    entries: tuple[Entry, ...]
    questions_by_version: Mapping[str, Sequence[Question]]


# ---------------------------------------------------------------------------
# skill_versions
# ---------------------------------------------------------------------------


def ensure_skill_versions(conn: sqlite3.Connection, skills_dir: Path) -> None:
    """skills_dir 直下の各 Skill（`<name>/SKILL.md`）の今の版を skill_versions に登録する。

    名前が SKILL_NAME_PATTERN に合わないディレクトリ・SKILL.md の無いディレクトリは
    飛ばす。Skill ごとに処理し、壊れた SKILL.md（SkillValidationError）・読めない
    （OSError）・同じ版が別の内容で登録済み（ValueError。版を上げずに書き換えた。
    黙って上書きしない）は、名前と型名だけを警告に残して次へ進む（起動を止めない）。
    skills_dir が無い（FileNotFoundError）・DB の失敗（sqlite3.Error）は外へ出す。
    何度呼んでもよい。
    """
    root = Path(skills_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"skills_dir が無い: {root}")
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        name = child.name
        if not (is_valid_skill_name(name) and (child / SKILL_FILE_NAME).is_file()):
            continue
        try:
            _register_skill(conn, root, name)
        except (SkillValidationError, OSError, ValueError) as exc:
            _log.warning(
                "skill %s を skill_versions に登録しない: %s", name, type(exc).__name__
            )


def _register_skill(conn: sqlite3.Connection, root: Path, name: str) -> None:
    text = read_skill_text(name, root)
    skill = validate_skill_text(name, text)
    questions = list(skill.questions) if isinstance(skill, RegimenSkill) else None
    db.save_skill_version(conn, skill.name, skill.version, text, questions)


def _parse_version(value: object) -> tuple[str, int] | None:
    """`"regimen-folfox@1"` → (名前, 版)。regimen Skill でない・形が違えば None。"""
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.fullmatch(value)
    if match is None or match["name"] not in REGIMEN_SKILL_NAMES.values():
        return None
    return match["name"], int(match["version"])


def _fetch_questions(
    conn: sqlite3.Connection, pairs: Iterable[tuple[str, int]]
) -> dict[str, list[Question]]:
    found: dict[str, list[Question]] = {}
    for name, version in sorted(set(pairs)):
        row = db.get_skill_version(conn, name, version)
        if row is not None and row["questions"] is not None:
            found[f"{name}@{version}"] = list(row["questions"])
    return found


def _scan_pairs(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """regimen Skill ごとに 1〜min(最新, 上限) の版と最新の版。"""
    pairs: list[tuple[str, int]] = []
    for name in sorted(REGIMEN_SKILL_NAMES.values()):
        latest = db.latest_skill_version(conn, name)
        if latest is None:
            continue
        top = int(latest["version"])
        if top > MAX_SCANNED_VERSIONS:
            _log.warning(
                "skill %s: 版 %d は MAX_SCANNED_VERSIONS を超える（途中は引かない）",
                name,
                top,
            )
        pairs.extend((name, v) for v in range(1, min(top, MAX_SCANNED_VERSIONS) + 1))
        pairs.append((name, top))
    return pairs


def questions_by_version(
    conn: sqlite3.Connection, versions: Iterable[str] | None = None
) -> dict[str, list[Question]]:
    """`"regimen-folfox@1"` → その版の質問集（regimen Skill の登録済みの版）。

    versions を渡せば、その版だけを引く（形の違う値・regimen でない Skill は無視）。
    渡さなければ regimen Skill ごとに 1〜min(最新, MAX_SCANNED_VERSIONS) と最新の版を引く
    （db に版の一覧を返す公開関数が無いための上限）。
    """
    if versions is None:
        return _fetch_questions(conn, _scan_pairs(conn))
    parsed = (_parse_version(v) for v in versions)
    return _fetch_questions(conn, (p for p in parsed if p is not None))


# ---------------------------------------------------------------------------
# 入力を集める
# ---------------------------------------------------------------------------


def _is_open(visit: Mapping[str, Any] | None) -> bool:
    """受付番号が残っていて期限（expires_at）前の受診か。

    purge_expired がまだ走っていなくても、期限を過ぎていれば閉じたものとして扱う
    （db の条件付き書き込みと同じ境界: expires_at > now の間だけ開いている）。
    """
    if visit is None or visit["reception_no"] is None:
        return False
    expires_at = visit["expires_at"]
    return expires_at is not None and expires_at > clock_now()


def _gather(
    conn: sqlite3.Connection, visit: Mapping[str, Any], settings: Settings
) -> _VisitInputs:
    patient_id = str(visit["patient_id"])
    patient = db.get_patient(conn, patient_id)
    if patient is None:
        raise LookupError("patient not found")
    regimen_skill = load_regimen_skill(patient["regimen"], settings.skills_dir)
    entries = tuple(db.list_entries(conn, patient_id))
    used = {e.skill_version for e in entries} | {regimen_skill.skill_version}
    return _VisitInputs(
        reception_no=str(visit["reception_no"]),
        patient_id=patient_id,
        visit_date=visit["visit_date"],
        regimen_skill=regimen_skill,
        report_skill=load_report_skill(skills_dir=settings.skills_dir),
        courses=tuple(db.list_courses(conn, patient_id)),
        entries=entries,
        questions_by_version=questions_by_version(conn, versions=sorted(used)),
    )


def _prepare(inputs: _VisitInputs, logger: EventLogger) -> PreparedInput:
    return prepare_input(
        courses=inputs.courses,
        entries=inputs.entries,
        regimen_skill=inputs.regimen_skill,
        report_skill=inputs.report_skill,
        visit_date=inputs.visit_date,
        exclude_literals=(inputs.patient_id, inputs.reception_no),
        logger=logger,
    )


# ---------------------------------------------------------------------------
# 組み立て・保存
# ---------------------------------------------------------------------------


def _fallback_result(code: str, stats: RunStats | None = None) -> ConversionResult:
    return ConversionResult(
        timeline=None,
        picks=None,
        fallback=True,
        error_code=code,
        stats=stats or RunStats(),
    )


def _render(
    inputs: _VisitInputs, prepared: PreparedInput, result: ConversionResult
) -> tuple[ReportData, str]:
    data = build_report_data(
        reception_no=inputs.reception_no,
        patient_id=inputs.patient_id,
        regimen_skill=inputs.regimen_skill,
        report_skill=inputs.report_skill,
        courses=inputs.courses,
        entries=inputs.entries,
        visit_date=inputs.visit_date,
        prepared=prepared,
        result=result,
        questions_by_version=inputs.questions_by_version,
    )
    skill = inputs.report_skill
    html = render_report_html(
        data,
        questions=list(inputs.regimen_skill.questions),
        low_confidence_threshold=skill.low_confidence_threshold,
        sections=list(skill.sections),
        quotes_max_items=skill.quotes_max_items,
    )
    return data, html


def _render_or_fallback(
    inputs: _VisitInputs,
    prepared: PreparedInput,
    result: ConversionResult,
    logger: EventLogger,
) -> tuple[ConversionResult, ReportData, str] | str:
    """AI の結果で組み立て、だめなら AI 変換なしで組み立て直す。

    両方だめなら最後の失敗のコード（`report_error:<型名>`）を返す（visit_failed は
    呼び出し側が、本当に failed にできたときだけ書く）。
    """
    attempts = [result]
    if not result.fallback:
        attempts.append(_fallback_result(REPORT_ERROR, result.stats))
    code = REPORT_ERROR
    for i, attempt in enumerate(attempts):
        try:
            data, html = _render(inputs, prepared, attempt)
        except Exception as exc:  # noqa: BLE001 — どこで失敗してもフォールバックへ
            code = reason_code(REPORT_ERROR, type(exc).__name__)
            _log.warning("report build failed: %s", type(exc).__name__)
            if i + 1 < len(attempts):
                logger.event("fallback", decision=code)
            continue
        return attempt, data, html
    return code


def _timeline_to_save(result: ConversionResult, prepared: PreparedInput) -> Timeline:
    if not result.fallback and result.timeline is not None:
        return result.timeline
    return Timeline(unprocessed_entries=list(prepared.unprocessed))


def _set_status_if_open(
    conn: sqlite3.Connection, visit_id: int, status: str, fallback: bool | None = None
) -> bool:
    """受付番号が残っていれば状態を変えて True。消えていれば（印刷済み等）触らず False。

    読み直しと更新を db の書き込みロックの中で行う（同じプロセスの mark_printed が
    間に入らない）。set_visit_status は条件付き更新なので、別プロセスの mark_printed
    に負けたとき（VisitClosedError）も閉じた受診として扱う。
    """
    with write_transaction(conn):
        if not _is_open(db.get_visit(conn, visit_id)):
            return False
        try:
            db.set_visit_status(conn, visit_id, status, fallback=fallback)
        except VisitClosedError:
            return False
    return True


def _mark_failed(
    conn: sqlite3.Connection, visit_id: int, logger: EventLogger, code: str
) -> None:
    """failed にする。読み直して受付番号が消えていれば（印刷済み等）触らない。"""
    try:
        changed = _set_status_if_open(conn, visit_id, "failed")
    except _DB_ERRORS as exc:
        _log.warning("visit %s: failed にできない: %s", visit_id, type(exc).__name__)
        return
    if not changed:
        logger.event("visit_closed")
        return
    logger.event("visit_failed", decision=code)


def _save(
    conn: sqlite3.Connection,
    visit_id: int,
    timeline: Timeline,
    data: ReportData,
    html: str,
) -> bool:
    """1つのトランザクションで保存して ready にする。印刷済みなら False（何も変えない）。"""
    try:
        db.save_visit_result(
            conn,
            visit_id,
            timeline=timeline,
            html=html,
            data=data,
            status="ready",
            fallback=data.fallback,
        )
    except VisitClosedError:
        return False
    return True


def _publish(
    conn: sqlite3.Connection,
    visit_id: int,
    inputs: _VisitInputs,
    prepared: PreparedInput,
    result: ConversionResult,
    logger: EventLogger,
) -> None:
    rendered = _render_or_fallback(inputs, prepared, result, logger)
    if isinstance(rendered, str):
        _mark_failed(conn, visit_id, logger, rendered)
        return
    used, data, html = rendered
    try:
        saved = _save(conn, visit_id, _timeline_to_save(used, prepared), data, html)
    except _DB_ERRORS as exc:
        _mark_failed(
            conn, visit_id, logger, reason_code(SAVE_ERROR, type(exc).__name__)
        )
        return
    if not saved:
        logger.event("visit_closed")
        return
    logger.event("visit_ready", decision="fallback" if data.fallback else "ok")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def _convert(
    prepared: PreparedInput,
    *,
    runner: AgentRunner,
    settings: Settings,
    logger: EventLogger,
) -> ConversionResult:
    """convert は例外を出さない契約。出たら（型名だけ残して）AI 変換なしにする。"""
    try:
        return await convert(prepared, runner=runner, logger=logger, settings=settings)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — どこで失敗してもフォールバックへ
        code = reason_code("convert_error", type(exc).__name__)
        logger.event("fallback", decision=code)
        logger.event("run_end", decision=code)
        return _fallback_result("convert_error")


async def generate_visit_report(
    conn: sqlite3.Connection,
    visit_id: int,
    *,
    runner: AgentRunner,
    settings: Settings,
    logger: EventLogger | None = None,
) -> None:
    """受診のレポートを作り ready（AI 変換なしなら fallback=True）か failed にする。"""
    try:
        visit = db.get_visit(conn, visit_id)
    except sqlite3.Error as exc:
        _log.warning("visit %s: 受診を読めない: %s", visit_id, type(exc).__name__)
        return
    if not _is_open(visit):
        _log.info("visit %s: 無い・印刷済み・期限切れのため生成しない", visit_id)
        return
    assert visit is not None
    log = logger if logger is not None else PipelineLogger(conn, RUN_KIND, visit_id)
    try:
        inputs = _gather(conn, visit, settings)
        prepared = _prepare(inputs, log)
    except Exception as exc:  # noqa: BLE001 — 入力が作れない → failed
        code = reason_code(PREPARE_ERROR, type(exc).__name__)
        _log.warning("visit %s: 入力を作れない: %s", visit_id, type(exc).__name__)
        log.event("run_start")
        log.event("run_end", decision=code)
        _mark_failed(conn, visit_id, log, code)
        return
    try:
        result = await _convert(prepared, runner=runner, settings=settings, logger=log)
    except asyncio.CancelledError:
        log.event("run_end", decision=CANCELLED)
        _mark_failed(conn, visit_id, log, CANCELLED)
        raise
    _publish(conn, visit_id, inputs, prepared, result, log)

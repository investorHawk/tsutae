"""対象を探して通知を送る1回分（同期の関数。周期タスクが `asyncio.to_thread` で呼ぶ）。

- `send_due_once`: 全ての登録を判定し（`decide`）、対象に送る。1件の失敗で止めない
- `send_test_once`: 試送。印・期間・時刻を見ず、その日の分（last_sent_date）も使わない
- 送信先が 404・410 を返した登録は消し、endpoint を覚える（端末が送り直してきたら断って伝える）
- 送る前に今日の分を取り（`claim_push_send`）、送れなければ戻す。窓（10 分）の間は次の周期で
  やり直せるが、窓を過ぎたら送らない。1回送れた後は送らない
- ログは件数と例外の型名だけ。仮名ID・endpoint・例外の文面を出さない（exc_info も付けない）
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from tsutae import db
from tsutae.config import Settings, now, to_jst_date
from tsutae.push.decide import decide_send, is_time_to_check
from tsutae.push.payload import notification_payload
from tsutae.push.sender import PushSender, PushSendError, PushTarget
from tsutae.skills import load_regimen_skill

__all__ = ["DeliveryResult", "PushCounts", "send_due_once", "send_test_once"]

DeliveryResult = Literal["sent", "gone", "failed"]
_GONE_STATUSES = frozenset({404, 410})
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushCounts:
    sent: int = 0
    gone: int = 0
    failed: int = 0
    skipped: int = 0


class _CycleDays:
    """レジメンごとの1コースの日数（1回の周期の間だけ覚える）。読めなければ None。"""

    def __init__(self, settings: Settings) -> None:
        self._skills_dir = settings.skills_dir
        self._known: dict[str, int | None] = {}

    def of(self, regimen: str) -> int | None:
        if regimen not in self._known:
            self._known[regimen] = self._read(regimen)
        return self._known[regimen]

    def _read(self, regimen: str) -> int | None:
        try:
            return load_regimen_skill(regimen, self._skills_dir).cycle_days
        except (
            Exception
        ) as exc:  # noqa: BLE001 — 読めない患者は飛ばす。他の患者を止めない
            _log.warning("push.skill_unreadable error_type=%s", type(exc).__name__)
            return None


def _deliver(
    sender: PushSender,
    subscription: db.PushSubscription,
    payload: str,
) -> DeliveryResult:
    target = PushTarget(
        endpoint=subscription.endpoint,
        p256dh=subscription.p256dh,
        auth=subscription.auth,
    )
    try:
        sender(target, payload)
    except PushSendError as exc:
        if exc.status_code in _GONE_STATUSES:
            return "gone"
        _log.warning("push.send_failed error_type=%s", type(exc).__name__)
        return "failed"
    except Exception as exc:  # noqa: BLE001 — 1件の失敗で他の端末を止めない
        _log.warning("push.send_failed error_type=%s", type(exc).__name__)
        return "failed"
    return "sent"


def _remove_gone(
    conn: sqlite3.Connection, subscription: db.PushSubscription, at: datetime
) -> None:
    db.delete_push_subscription_by_id(conn, subscription.id)
    db.mark_push_endpoint_gone(conn, subscription.endpoint, at)


def _due_decision(
    conn: sqlite3.Connection,
    subscription: db.PushSubscription,
    at: datetime,
    marked: set[str],
    cycles: _CycleDays,
) -> str | None:
    """判定のコード。Skill が読めず判定できなければ None。"""
    is_marked = subscription.patient_id in marked
    courses = db.list_courses(conn, subscription.patient_id)
    last = max(courses, key=lambda c: c.course_no) if courses else None
    cycle_days = None
    if last is not None and not is_marked:
        patient = db.get_patient(conn, subscription.patient_id)
        cycle_days = cycles.of(patient["regimen"]) if patient else None
        if cycle_days is None:
            return None
    return decide_send(
        at,
        notify_time=subscription.notify_time,
        last_sent_date=subscription.last_sent_date,
        marked_today=is_marked,
        last_day1=last.infusion_date if last is not None else None,
        cycle_days=cycle_days,
    )


def _send_daily(
    conn: sqlite3.Connection,
    sender: PushSender,
    subscription: db.PushSubscription,
    at: datetime,
    payload: str,
) -> str:
    day = to_jst_date(at)
    if not db.claim_push_send(conn, subscription.id, day):
        return "skipped"
    result = _deliver(sender, subscription, payload)
    if result != "sent":
        # 届いていないので今日の分を戻す（消すときに「送った」と残さない）
        db.release_push_send(conn, subscription.id, day, subscription.last_sent_date)
    if result == "gone":
        _remove_gone(conn, subscription, at)
    return result


def _process_one(
    conn: sqlite3.Connection,
    sender: PushSender,
    subscription: db.PushSubscription,
    at: datetime,
    marked: set[str],
    cycles: _CycleDays,
    payload: str,
) -> str | None:
    """1件の結果（sent・gone・failed・skipped）。対象でなければ None。"""
    if not is_time_to_check(at, subscription.notify_time, subscription.last_sent_date):
        return None
    decision = _due_decision(conn, subscription, at, marked, cycles)
    if decision is None:
        return "skipped"
    if decision != "due":
        return None
    return _send_daily(conn, sender, subscription, at, payload)


def send_due_once(
    settings: Settings, sender: PushSender, at: datetime | None = None
) -> PushCounts:
    """対象の登録に1回ずつ送り、件数を返す。at を省くと今（`config.now()`）。"""
    current = at if at is not None else now()
    payload = notification_payload()
    cycles = _CycleDays(settings)
    results: Counter[str] = Counter()
    conn = db.connect(settings.db_path)
    try:
        marked = db.marked_patients(conn, to_jst_date(current))
        for subscription in db.list_push_subscriptions(conn):
            try:
                result = _process_one(
                    conn, sender, subscription, current, marked, cycles, payload
                )
            except Exception as exc:  # noqa: BLE001 — 1件の失敗で他の端末を止めない
                _log.warning("push.check_failed error_type=%s", type(exc).__name__)
                result = "failed"
            if result is not None:
                results[result] += 1
    finally:
        conn.close()
    counts = PushCounts(**results)
    if results:
        _log.info(
            "push.done sent=%d gone=%d failed=%d skipped=%d",
            counts.sent,
            counts.gone,
            counts.failed,
            counts.skipped,
        )
    return counts


def send_test_once(
    settings: Settings, sender: PushSender, subscription_id: int
) -> DeliveryResult | None:
    """試送を1通送る。登録がもう無ければ None（待つ間にオフにした）。"""
    conn = db.connect(settings.db_path)
    try:
        subscription = db.get_push_subscription_by_id(conn, subscription_id)
        if subscription is None:
            return None
        result = _deliver(sender, subscription, notification_payload())
        if result == "gone":
            _remove_gone(conn, subscription, now())
        return result
    finally:
        conn.close()

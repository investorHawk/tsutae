"""通知を送るかどうかの判定（純関数。DB・時計に触れない）。

plan-device-records §4.1 の決まり:

- 1日1回まで（last_sent_date が今日なら送らない）
- notify_time の前は送らない。notify_time から 10 分を超えたらその日は送らない
  （サーバーが止まっていた分を後から送り直さない）
- 今日の印があれば送らない（どの端末で書いても）
- コースが無ければ送らない。最後のコースの Day1 + cycle_days + 14 日を過ぎたら送らない

日付と時刻は JST で見る。notify_time は 00:00〜23:30 なので窓が日をまたぐことは無い。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Literal

from tsutae.config import JST

__all__ = ["GRACE_DAYS", "SEND_WINDOW", "Decision", "decide_send", "is_time_to_check"]

GRACE_DAYS = 14  # 1コースの日数の後、延期に備えて送り続ける日数
SEND_WINDOW = timedelta(minutes=10)

Decision = Literal[
    "due",
    "sent_today",
    "before_time",
    "window_passed",
    "marked",
    "no_course",
    "period_over",
]

_NOTIFY_TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


def _local(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("at は tz 付きの日時")
    return at.astimezone(JST)


def _notify_at(at: datetime, notify_time: str) -> datetime:
    if not _NOTIFY_TIME_RE.fullmatch(notify_time):
        raise ValueError("notify_time は HH:MM")
    return datetime.combine(at.date(), time.fromisoformat(notify_time), tzinfo=JST)


def _time_decision(
    at: datetime, notify_time: str, last_sent_date: date | None
) -> Decision | None:
    """時刻と送信済みだけの判定。ここで止まらなければ None。"""
    start = _notify_at(at, notify_time)
    if last_sent_date == at.date():
        return "sent_today"
    if at < start:
        return "before_time"
    if at > start + SEND_WINDOW:
        return "window_passed"
    return None


def is_time_to_check(
    at: datetime, notify_time: str, last_sent_date: date | None
) -> bool:
    """いま判定を続ける登録か（Skill を読む前の絞り込み。印もコースも見ない）。"""
    return _time_decision(_local(at), notify_time, last_sent_date) is None


def decide_send(
    at: datetime,
    *,
    notify_time: str,
    last_sent_date: date | None,
    marked_today: bool,
    last_day1: date | None,
    cycle_days: int | None,
) -> Decision:
    """送るなら "due"、送らないなら理由のコード。

    last_day1 は最後のコース（course_no が最大）の Day1。コースがあるのに cycle_days が
    無ければ ValueError（読めない Skill の患者は呼び出し側で飛ばす）。
    """
    local = _local(at)
    stopped = _time_decision(local, notify_time, last_sent_date)
    if stopped is not None:
        return stopped
    if marked_today:
        return "marked"
    if last_day1 is None:
        return "no_course"
    if cycle_days is None:
        raise ValueError("コースがあるのに cycle_days が無い")
    if local.date() > last_day1 + timedelta(days=cycle_days + GRACE_DAYS):
        return "period_over"
    return "due"

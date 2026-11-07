"""通知の本文（plan-device-records §4.1。文は patient_strings.json の固定文だけ）。"""

from __future__ import annotations

import json

from tsutae.config import PATIENT_STRINGS_PATH
from tsutae.push.payload import notification_payload


def _strings() -> dict[str, str]:
    return json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))


def test_wording_is_the_one_in_the_spec() -> None:
    strings = _strings()
    assert strings["notify.title"] == "つたえ"
    assert strings["notify.body"] == (
        "今日の記録をお願いします。つらい日はボタンひとつで記録になります。"
    )


def test_payload_is_json_with_fixed_fields() -> None:
    strings = _strings()
    assert json.loads(notification_payload()) == {
        "title": strings["notify.title"],
        "body": strings["notify.body"],
        "url": "/today",
        "badge": 1,
    }


def test_payload_is_small_enough_for_web_push() -> None:
    """Web Push の本文の上限（約 4KB）より十分小さい。"""
    assert len(notification_payload().encode("utf-8")) < 1024

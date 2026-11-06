"""通知の本文。文は patient_strings.json の固定文だけで、患者ごとに変わらない。

症状・レジメン名・薬の名前・AI の文を入れない（引数を取らないのはそのため）。
"""

from __future__ import annotations

import json

from tsutae.patient_strings import load_patient_strings

__all__ = ["notification_payload"]


def notification_payload() -> str:
    """Service Worker に渡す JSON（title・body・url・badge）。"""
    strings = load_patient_strings()
    return json.dumps(
        {
            "title": strings["notify.title"],
            "body": strings["notify.body"],
            "url": "/today",
            "badge": 1,
        },
        ensure_ascii=False,
    )

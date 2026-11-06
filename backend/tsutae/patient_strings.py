"""患者向けの定型文（patient_strings.json）の読み込み。患者 API と通知が使う。"""

from __future__ import annotations

import json
from functools import lru_cache

from tsutae.config import PATIENT_STRINGS_PATH

__all__ = ["load_patient_strings"]


@lru_cache(maxsize=1)
def load_patient_strings() -> dict[str, str]:
    data = json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError("patient_strings.json は文字列→文字列の対応")
    return data

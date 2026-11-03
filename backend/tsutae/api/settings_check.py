"""起動時の設定の検査（署名鍵・医師パスワード）。

- 既定の署名鍵・既定の医師パスワードは公開されているので、そのままでは医師 Cookie と
  患者 Cookie を誰でも作れる。public_base_url のホストが localhost / 127.0.0.1 / ::1
  でなければ `InsecureSettingsError` で起動を止める。手元（localhost）では警告だけ
- 空の署名鍵も同じ扱い。16 字未満の鍵は警告だけ（止めない）
- ログには理由のコードだけを出す（鍵・パスワードの値は出さない）
- 既定値は `tsutae.config.get_settings` の既定と同じもの（テストで一致を確かめる）
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from tsutae.config import Settings

__all__ = [
    "DEFAULT_DOCTOR_PASSWORD",
    "DEFAULT_SECRET",
    "InsecureSettingsError",
    "MIN_SECRET_LENGTH",
    "check_settings",
    "insecure_reasons",
    "is_local_url",
]

DEFAULT_SECRET = "dev-secret-change-me"
DEFAULT_DOCTOR_PASSWORD = "demo-doctor"
MIN_SECRET_LENGTH = 16
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
BLOCKING = frozenset({"default_secret", "empty_secret", "default_doctor_password"})
_log = logging.getLogger(__name__)


class InsecureSettingsError(RuntimeError):
    """公開の構成で、既定（公開済み）の鍵やパスワードのまま起動しようとした。"""


def is_local_url(url: str) -> bool:
    """URL のホストが localhost / 127.0.0.1 / ::1 か（部分一致にしない）。"""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    return host is not None and host.lower() in LOCAL_HOSTS


def insecure_reasons(settings: Settings) -> list[str]:
    """設定の弱いところのコード（無ければ空）。"""
    reasons = []
    if settings.secret_key == DEFAULT_SECRET:
        reasons.append("default_secret")
    elif not settings.secret_key:
        reasons.append("empty_secret")
    elif len(settings.secret_key) < MIN_SECRET_LENGTH:
        reasons.append("short_secret")
    if settings.doctor_password == DEFAULT_DOCTOR_PASSWORD:
        reasons.append("default_doctor_password")
    return reasons


def check_settings(settings: Settings) -> None:
    """公開の構成で既定値なら止める。それ以外の弱いところは警告ログ。"""
    reasons = insecure_reasons(settings)
    if not reasons:
        return
    blocking = sorted(BLOCKING.intersection(reasons))
    if blocking and not is_local_url(settings.public_base_url):
        raise InsecureSettingsError(
            "TSUTAE_SECRET / DOCTOR_PASSWORD を既定値から変えてください: "
            + ",".join(blocking)
        )
    _log.warning("settings.insecure reasons=%s", ",".join(reasons))

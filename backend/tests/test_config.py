from datetime import date, datetime

import pytest

from tsutae import config


def test_today_can_be_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")
    assert config.today() == date(2026, 11, 9)
    assert config.now().date() == date(2026, 11, 9)
    assert config.now().tzinfo is not None


def test_to_jst_date_crosses_midnight() -> None:
    # UTC 15:30 は JST 翌日 0:30
    utc = datetime.fromisoformat("2026-11-08T15:30:00+00:00")
    assert config.to_jst_date(utc) == date(2026, 11, 9)


def test_load_env_file_missing_is_false(tmp_path) -> None:
    assert config.load_env_file(tmp_path / "nope.env") is False


def test_fixed_today_clock_moves_forward(monkeypatch) -> None:
    # TSUTAE_TODAY の時計は固定日から実時間で進む（日をまたげば翌日になり、TTL が働く）
    from datetime import datetime, timedelta

    real = [datetime(2026, 11, 4, 23, 0, tzinfo=config.JST)]

    class _Clock:
        @staticmethod
        def now(tz=None):
            return real[0]

        def __getattr__(self, name):
            return getattr(datetime, name)

    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")
    monkeypatch.setattr(config, "_FIXED_ANCHORS", {})
    monkeypatch.setattr(config, "datetime", _Clock())
    first = config.now()
    assert first == datetime(2026, 11, 9, 23, 0, tzinfo=config.JST)
    assert config.today() == date(2026, 11, 9)
    real[0] = real[0] + timedelta(hours=2)
    assert config.now() == datetime(2026, 11, 10, 1, 0, tzinfo=config.JST)
    assert config.today() == date(2026, 11, 10)


def test_regimen_turn_timeout_default_and_env(monkeypatch) -> None:
    monkeypatch.delenv("TSUTAE_REGIMEN_TURN_TIMEOUT_S", raising=False)
    assert config.get_settings().regimen_turn_timeout_s == 90.0
    monkeypatch.setenv("TSUTAE_REGIMEN_TURN_TIMEOUT_S", "45")
    assert config.get_settings().regimen_turn_timeout_s == 45.0


def test_regimen_chat_limits_default_and_env(monkeypatch) -> None:
    for name in (
        "TSUTAE_REGIMEN_MAX_TURNS",
        "TSUTAE_REGIMEN_MAX_BUDGET_USD",
        "TSUTAE_REGIMEN_TURN_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = config.get_settings()
    assert settings.regimen_max_turns == 12
    assert settings.regimen_max_budget_usd == 1.0
    # 回復（working を open に戻す）は往復の上限に余裕を足してから
    assert config.REGIMEN_RECOVER_GRACE_S == 15.0
    assert settings.regimen_recover_after_s == 105.0
    monkeypatch.setenv("TSUTAE_REGIMEN_MAX_TURNS", "5")
    monkeypatch.setenv("TSUTAE_REGIMEN_MAX_BUDGET_USD", "0.3")
    monkeypatch.setenv("TSUTAE_REGIMEN_TURN_TIMEOUT_S", "45")
    settings = config.get_settings()
    assert (settings.regimen_max_turns, settings.regimen_max_budget_usd) == (5, 0.3)
    assert settings.regimen_recover_after_s == 60.0


def test_vapid_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PUBLIC", "PRIVATE"):
        monkeypatch.delenv(f"TSUTAE_VAPID_{name}_KEY", raising=False)
    monkeypatch.delenv("TSUTAE_VAPID_SUBJECT", raising=False)
    settings = config.get_settings()
    assert settings.vapid_public_key is None
    assert settings.vapid_private_key is None
    assert settings.vapid_subject is None
    monkeypatch.setenv("TSUTAE_VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("TSUTAE_VAPID_PRIVATE_KEY", "vapid-private-value")
    monkeypatch.setenv("TSUTAE_VAPID_SUBJECT", "mailto:a@example.com")
    settings = config.get_settings()
    assert settings.vapid_public_key == "pub"
    assert settings.vapid_private_key == "vapid-private-value"
    assert settings.vapid_subject == "mailto:a@example.com"
    assert "vapid-private-value" not in repr(settings)

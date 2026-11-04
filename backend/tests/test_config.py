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

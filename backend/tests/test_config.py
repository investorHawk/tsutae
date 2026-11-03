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

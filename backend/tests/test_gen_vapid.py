"""scripts/gen_vapid.py: 鍵を標準出力に出すだけで、出した鍵は組になっている。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from api_helpers import make_settings

from tsutae.config import REPO_ROOT
from tsutae.push.sender import load_vapid

SCRIPT = REPO_ROOT / "scripts" / "gen_vapid.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_vapid", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lines(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def test_output_is_a_working_key_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _load().main() == 0
    values = _lines(capsys.readouterr().out)
    assert set(values) == {
        "TSUTAE_VAPID_PUBLIC_KEY",
        "TSUTAE_VAPID_PRIVATE_KEY",
        "TSUTAE_VAPID_SUBJECT",
    }
    assert values["TSUTAE_VAPID_SUBJECT"].startswith("mailto:")
    settings = make_settings(
        tmp_path,
        vapid_public_key=values["TSUTAE_VAPID_PUBLIC_KEY"],
        vapid_private_key=values["TSUTAE_VAPID_PRIVATE_KEY"],
        vapid_subject=values["TSUTAE_VAPID_SUBJECT"],
    )
    assert load_vapid(settings) is not None


def test_each_run_makes_new_keys(capsys: pytest.CaptureFixture[str]) -> None:
    module = _load()
    module.main()
    first = _lines(capsys.readouterr().out)
    module.main()
    second = _lines(capsys.readouterr().out)
    assert first["TSUTAE_VAPID_PRIVATE_KEY"] != second["TSUTAE_VAPID_PRIVATE_KEY"]


def test_writes_no_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _load().main()
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []

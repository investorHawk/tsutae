"""設定と時計。

- `.env` はサンドボックス内では読み取りが拒否される（PermissionError）。その場合は
  「キーなし」として扱い、例外を外へ出さない
- 日付は全て Asia/Tokyo。デモ用に `TSUTAE_TODAY`（YYYY-MM-DD）で「今日」を固定できる
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
PACKAGE_ROOT = Path(__file__).resolve().parent
SKILLS_HOME = BACKEND_ROOT / "skills_home"
SKILLS_DIR = SKILLS_HOME / ".claude" / "skills"
DATA_DIR = REPO_ROOT / "data"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
PATIENT_STRINGS_PATH = PACKAGE_ROOT / "patient_strings.json"

DEFAULT_MODEL = "claude-opus-5-5"
SUBAGENT_MODEL = "claude-sonnet-5-5"
# 往復の上限を過ぎた working を open に戻すまでの余裕（秒）。往復の処理が上限ちょうどで
# 自分の結果・失敗の行を書く前に、別の読み出しが回復してしまわないように
REGIMEN_RECOVER_GRACE_S = 15.0


def load_env_file(path: Path | None = None) -> bool:
    """`.env` を環境変数に読み込む。読めなければ False（例外は出さない）。"""
    target = path or (REPO_ROOT / ".env")
    try:
        from dotenv import load_dotenv

        return bool(load_dotenv(target, override=False))
    except (PermissionError, OSError):
        return False


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@dataclass(frozen=True)
class Settings:
    db_path: Path
    doctor_password: str
    secret_key: str
    model: str
    subagent_model: str
    report_ttl_hours: int
    pipeline_timeout_s: float
    pipeline_max_turns: int
    pipeline_max_budget_usd: float
    skills_dir: Path
    public_base_url: str
    # D4 レジメンの Claude の1往復の上限（秒。T94）。working のまま過ぎた下書きは open に戻す
    regimen_turn_timeout_s: float = 90.0
    # 1往復の max_turns・max_budget_usd（T94）
    regimen_max_turns: int = 12
    regimen_max_budget_usd: float = 1.0

    @property
    def regimen_recover_after_s(self) -> float:
        """working のまま何秒で取り残しとみなすか（往復の上限＋余裕）。"""
        return self.regimen_turn_timeout_s + REGIMEN_RECOVER_GRACE_S


def get_settings() -> Settings:
    return Settings(
        db_path=Path(os.environ.get("TSUTAE_DB", str(DATA_DIR / "tsutae.db"))),
        doctor_password=os.environ.get("DOCTOR_PASSWORD", "demo-doctor"),
        secret_key=os.environ.get("TSUTAE_SECRET", "dev-secret-change-me"),
        model=os.environ.get("TSUTAE_MODEL", DEFAULT_MODEL),
        subagent_model=os.environ.get("TSUTAE_SUBAGENT_MODEL", SUBAGENT_MODEL),
        report_ttl_hours=int(os.environ.get("TSUTAE_REPORT_TTL_HOURS", "24")),
        pipeline_timeout_s=float(os.environ.get("TSUTAE_PIPELINE_TIMEOUT_S", "600")),
        pipeline_max_turns=int(os.environ.get("TSUTAE_PIPELINE_MAX_TURNS", "30")),
        pipeline_max_budget_usd=float(
            os.environ.get("TSUTAE_PIPELINE_MAX_BUDGET_USD", "3.0")
        ),
        skills_dir=Path(os.environ.get("TSUTAE_SKILLS_DIR", str(SKILLS_DIR))),
        public_base_url=os.environ.get(
            "TSUTAE_PUBLIC_BASE_URL", "http://localhost:5173"
        ),
        regimen_turn_timeout_s=float(
            os.environ.get("TSUTAE_REGIMEN_TURN_TIMEOUT_S", "90")
        ),
        regimen_max_turns=int(os.environ.get("TSUTAE_REGIMEN_MAX_TURNS", "12")),
        regimen_max_budget_usd=float(
            os.environ.get("TSUTAE_REGIMEN_MAX_BUDGET_USD", "1.0")
        ),
    )


# TSUTAE_TODAY の値ごとに「初めて使った実時刻」を覚える（固定日の時計の起点）
_FIXED_ANCHORS: dict[str, datetime] = {}


def today() -> date:
    """JST の今日。`TSUTAE_TODAY` があれば、その日から始まる時計（now）の日付。"""
    return now().date()


def now() -> datetime:
    """JST の現在時刻（tz-aware）。

    `TSUTAE_TODAY` があれば、その日の「初めて使った時の時刻」から実時間で進む時計にする
    （デモ・テスト用）。日をまたげば翌日になるので、24時間 TTL も働く。
    """
    current = datetime.now(JST)
    fixed = os.environ.get("TSUTAE_TODAY")
    if not fixed:
        return current
    fixed_date = date.fromisoformat(fixed)
    anchor = _FIXED_ANCHORS.setdefault(fixed, current)
    start = datetime.combine(fixed_date, anchor.timetz())
    return start + (current - anchor)


def to_jst_date(value: datetime) -> date:
    """tz-aware の日時を JST の日付に直す。naive は JST とみなす。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=JST)
    return value.astimezone(JST).date()


def jst_datetime(d: date, hh: int = 0, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=JST)

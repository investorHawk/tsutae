"""SQLite の保存層（docs/architecture.md §2）。公開関数はここから import する。

- 日時は JST の ISO 8601（+09:00）で保存し、dict で返すときは datetime に戻す
- 日付は YYYY-MM-DD で保存し、date に戻す。フラグ（fallback 等）は bool
- 書き込みは `write_transaction`（プロセス内ロック＋`with conn:`）、SQL はプレースホルダのみ
- 接続はリクエスト・タスクごとに `connect` するのを推奨（connection.py の注意を参照）
"""

from tsutae.db.connection import NotFoundError, VisitClosedError, connect, init_db
from tsutae.db.repo_entries import add_entry, get_entry, list_entries
from tsutae.db.repo_logs import add_pipeline_log, list_pipeline_logs
from tsutae.db.repo_patients import (
    create_patient,
    get_patient,
    list_courses,
    list_patients,
    upsert_course,
)
from tsutae.db.repo_skills import (
    create_skill_change,
    get_skill_change,
    get_skill_version,
    latest_skill_version,
    list_skill_changes,
    save_skill_version,
    update_skill_change,
)
from tsutae.db.repo_visits import (
    create_visit,
    get_report,
    get_timeline,
    get_visit,
    list_visits,
    mark_printed,
    purge_expired,
    save_report,
    save_timeline,
    set_visit_status,
)

__all__ = [
    "NotFoundError",
    "VisitClosedError",
    "add_entry",
    "add_pipeline_log",
    "connect",
    "create_patient",
    "create_skill_change",
    "create_visit",
    "get_entry",
    "get_patient",
    "get_report",
    "get_skill_change",
    "get_skill_version",
    "get_timeline",
    "get_visit",
    "init_db",
    "latest_skill_version",
    "list_courses",
    "list_entries",
    "list_patients",
    "list_pipeline_logs",
    "list_skill_changes",
    "list_visits",
    "mark_printed",
    "purge_expired",
    "save_report",
    "save_skill_version",
    "save_timeline",
    "set_visit_status",
    "update_skill_change",
    "upsert_course",
]

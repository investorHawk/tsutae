"""SQLite の保存層（docs/architecture.md §2）。公開関数はここから import する。

- 日時は JST の ISO 8601（+09:00）で保存し、dict で返すときは datetime に戻す
- 日付は YYYY-MM-DD で保存し、date に戻す。フラグ（fallback 等）は bool
- 書き込みは `write_transaction`（プロセス内ロック＋`with conn:`）、SQL はプレースホルダのみ。
  入れ子にすると内側の `with conn:` が commit するので、複数の書き込みを1つに
  まとめるときは専用の関数（save_visit_result・seed_patient）を使う
- 接続はリクエスト・タスクごとに `connect` するのを推奨（connection.py の注意を参照）
"""

from tsutae.db.connection import (
    NotFoundError,
    VisitClosedError,
    connect,
    init_db,
    write_transaction,
)
from tsutae.db.repo_entries import (
    add_entry,
    add_entry_once,
    get_entry,
    last_record_dates,
    list_entries,
    undo_too_sick_entry,
)
from tsutae.db.repo_logs import add_pipeline_log, list_pipeline_logs
from tsutae.db.repo_patients import (
    PATIENT_ID_PATTERN,
    create_patient,
    get_patient,
    list_courses,
    list_patients,
    upsert_course,
)
from tsutae.db.repo_seed import seed_patient
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
    begin_regeneration,
    create_visit,
    create_visit_once,
    get_report,
    get_timeline,
    get_visit,
    list_visits,
    mark_printed,
    purge_expired,
    save_report,
    save_timeline,
    save_visit_result,
    set_visit_status,
)

__all__ = [
    "NotFoundError",
    "PATIENT_ID_PATTERN",
    "VisitClosedError",
    "add_entry",
    "add_entry_once",
    "add_pipeline_log",
    "begin_regeneration",
    "connect",
    "create_patient",
    "create_skill_change",
    "create_visit",
    "create_visit_once",
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
    "last_record_dates",
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
    "save_visit_result",
    "seed_patient",
    "set_visit_status",
    "undo_too_sick_entry",
    "update_skill_change",
    "upsert_course",
    "write_transaction",
]

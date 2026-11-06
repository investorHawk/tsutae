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
    VisitAlreadyPrintedError,
    VisitClosedError,
    connect,
    init_db,
    write_transaction,
)
from tsutae.db.repo_doctor_masks import (
    VisitGeneratingError,
    list_doctor_masks,
    save_doctor_masks,
)
from tsutae.db.repo_entries import (
    add_entry,
    get_entry,
    list_entries,
)
from tsutae.db.repo_logs import add_pipeline_log, list_pipeline_logs
from tsutae.db.repo_patients import (
    PATIENT_ID_PATTERN,
    create_patient,
    get_patient,
    list_courses,
    list_patients,
    regimen_has_patients,
    upsert_course,
)
from tsutae.db.repo_push import (
    MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT,
    PushSubscription,
    claim_push_send,
    delete_push_subscription,
    delete_push_subscription_by_id,
    get_push_subscription,
    get_push_subscription_by_id,
    is_push_endpoint_gone,
    list_push_subscriptions,
    mark_push_endpoint_gone,
    release_push_send,
    upsert_push_subscription,
)
from tsutae.db.repo_question_library import (
    QuestionConflictError,
    QuestionInputError,
    add_library_question,
    get_library_question,
    hide_library_question,
    list_library_questions,
    seed_question_library,
)
from tsutae.db.repo_received import ReceivedEntry
from tsutae.db.repo_record_marks import (
    add_record_mark,
    backfill_record_marks,
    last_record_dates,
    list_record_marks,
    marked_patients,
    undo_record_mark,
)
from tsutae.db.repo_seed import seed_patient
from tsutae.db.repo_skills import (
    create_skill_change,
    get_skill_change,
    get_skill_version,
    insert_skill_version_row,
    latest_skill_version,
    list_skill_changes,
    list_skill_names,
    save_skill_version,
    update_skill_change,
)
from tsutae.db.repo_visit_regen import (
    REGEN_AUTO_MAX,
    clear_regen_pending,
    take_regen_pending,
)
from tsutae.db.repo_visits import (
    VisitReceipt,
    begin_regeneration,
    create_visit,
    create_visit_once,
    get_report,
    get_timeline,
    get_visit,
    list_visit_days,
    list_visits,
    mark_printed,
    purge_expired,
    save_report,
    save_timeline,
    save_visit_result,
    set_visit_status,
)

__all__ = [
    "MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT",
    "REGEN_AUTO_MAX",
    "NotFoundError",
    "PATIENT_ID_PATTERN",
    "PushSubscription",
    "QuestionConflictError",
    "QuestionInputError",
    "ReceivedEntry",
    "VisitAlreadyPrintedError",
    "VisitClosedError",
    "VisitReceipt",
    "VisitGeneratingError",
    "add_entry",
    "add_library_question",
    "add_pipeline_log",
    "add_record_mark",
    "backfill_record_marks",
    "begin_regeneration",
    "claim_push_send",
    "clear_regen_pending",
    "connect",
    "create_patient",
    "create_skill_change",
    "create_visit",
    "create_visit_once",
    "delete_push_subscription",
    "delete_push_subscription_by_id",
    "get_entry",
    "get_library_question",
    "get_patient",
    "get_push_subscription",
    "get_push_subscription_by_id",
    "get_report",
    "get_skill_change",
    "get_skill_version",
    "get_timeline",
    "get_visit",
    "hide_library_question",
    "init_db",
    "insert_skill_version_row",
    "latest_skill_version",
    "list_skill_names",
    "list_courses",
    "list_doctor_masks",
    "last_record_dates",
    "list_entries",
    "list_library_questions",
    "list_patients",
    "list_pipeline_logs",
    "is_push_endpoint_gone",
    "list_push_subscriptions",
    "list_record_marks",
    "mark_push_endpoint_gone",
    "list_skill_changes",
    "list_visit_days",
    "list_visits",
    "mark_printed",
    "marked_patients",
    "purge_expired",
    "regimen_has_patients",
    "release_push_send",
    "save_doctor_masks",
    "save_report",
    "save_skill_version",
    "save_timeline",
    "save_visit_result",
    "seed_patient",
    "seed_question_library",
    "set_visit_status",
    "take_regen_pending",
    "undo_record_mark",
    "update_skill_change",
    "upsert_course",
    "upsert_push_subscription",
    "write_transaction",
]

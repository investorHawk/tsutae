-- つたえ SQLite スキーマ（docs/architecture.md §2）。
-- 日時は JST の ISO 8601（+09:00、マイクロ秒まで固定幅）、日付は YYYY-MM-DD。
-- init_db が何度流しても安全なように IF NOT EXISTS のみを使う。

CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    regimen TEXT NOT NULL CHECK (regimen IN ('FOLFOX', 'CAPOX')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id),
    course_no INTEGER NOT NULL CHECK (course_no >= 1),
    infusion_date TEXT NOT NULL,
    planned_date TEXT,
    next_visit TEXT,
    note TEXT,
    UNIQUE (patient_id, course_no)
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id),
    recorded_at TEXT NOT NULL,
    record_date TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('too_sick', 'answers', 'free_text', 'mixed')),
    by_proxy INTEGER NOT NULL DEFAULT 0 CHECK (by_proxy IN (0, 1)),
    skill_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_patient_date
    ON entries (patient_id, record_date, recorded_at);

-- rowid を残す（WITHOUT ROWID にしない）。回答の挿入順を rowid で引く
CREATE TABLE IF NOT EXISTS closed_answers (
    entry_id INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    question_key TEXT NOT NULL,
    value TEXT NOT NULL
        CHECK (value IN ('none', 'present', 'hard', 'not_measured', 'measured')),
    temperature REAL,
    PRIMARY KEY (entry_id, question_key),
    CHECK ((value = 'measured') = (temperature IS NOT NULL))
);

-- 原文。Claude には送らない（送るのは伏せ字後）
CREATE TABLE IF NOT EXISTS free_texts (
    entry_id INTEGER PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    text TEXT NOT NULL
);

-- reception_no は印刷済み・期限切れで NULL にする
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id),
    reception_no TEXT,
    visit_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'generating'
        CHECK (status IN ('generating', 'ready', 'printed', 'failed')),
    expires_at TEXT NOT NULL,
    fallback INTEGER NOT NULL DEFAULT 0 CHECK (fallback IN (0, 1)),
    course_no INTEGER
);

CREATE INDEX IF NOT EXISTS idx_visits_status_expires ON visits (status, expires_at);

CREATE TABLE IF NOT EXISTS timelines (
    visit_id INTEGER PRIMARY KEY REFERENCES visits (id) ON DELETE CASCADE,
    json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    visit_id INTEGER PRIMARY KEY REFERENCES visits (id) ON DELETE CASCADE,
    html TEXT NOT NULL,
    data_json TEXT NOT NULL
);

-- 文面（プロンプト・記録・引用・出力）は入れない。識別子と数値だけ
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id INTEGER PRIMARY KEY,
    run_kind TEXT NOT NULL CHECK (run_kind IN ('visit', 'skill_change')),
    run_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    hook_name TEXT,
    agent_type TEXT,
    tool_name TEXT,
    decision TEXT,
    duration_ms INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL
);

CREATE INDEX IF NOT EXISTS idx_pipeline_logs_run
    ON pipeline_logs (run_kind, run_id, id);

CREATE TABLE IF NOT EXISTS skill_changes (
    id INTEGER PRIMARY KEY,
    skill_name TEXT NOT NULL,
    requested_text TEXT NOT NULL,
    diff TEXT,
    new_text TEXT,
    base_version INTEGER NOT NULL,
    new_version INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'failed')),
    error_code TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

-- その日の記録に使った質問集のスナップショット（未設問「−−」の表示に使う）
CREATE TABLE IF NOT EXISTS skill_versions (
    skill_name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content TEXT NOT NULL,
    questions_json TEXT,
    approved_at TEXT NOT NULL,
    PRIMARY KEY (skill_name, version)
);

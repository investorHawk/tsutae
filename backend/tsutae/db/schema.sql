-- つたえ SQLite スキーマ（docs/architecture.md §2）。
-- 日時は JST の ISO 8601（+09:00、マイクロ秒まで固定幅）、日付は YYYY-MM-DD。
-- init_db が何度流しても安全なように IF NOT EXISTS のみを使う。

-- regimen はレジメンの識別名（v1.1。FOLFOX/CAPOX に固定しない。一覧との照合は API の入口、
-- 書式は repo_patients。既存の DB の CHECK は migrate_db が外す）
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    regimen TEXT NOT NULL,
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

-- 医師の伏せ字（D6）。受診ごと・記録ごと。位置（原文の区間・許す区間）と確かめの真偽
-- だけを持ち、文面は持たない。生の記録（entries・free_texts）は変えない。印刷済み・
-- 期限切れでレポートと同じトランザクションで消す（spec 13.3）
CREATE TABLE IF NOT EXISTS doctor_masks (
    visit_id INTEGER NOT NULL REFERENCES visits (id) ON DELETE CASCADE,
    entry_id INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    spans_json TEXT NOT NULL,
    confirmed_clear INTEGER NOT NULL DEFAULT 0 CHECK (confirmed_clear IN (0, 1)),
    allowed_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    PRIMARY KEY (visit_id, entry_id)
);

-- 文面（プロンプト・記録・引用・出力）は入れない。識別子と数値だけ
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id INTEGER PRIMARY KEY,
    run_kind TEXT NOT NULL
        CHECK (run_kind IN ('visit', 'skill_change', 'regimen_chat')),
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

-- 質問の部品集（v1.1。spec 9.1）。D4 レジメンの画面の小窓で選ぶ候補。SKILL.md には影響しない。
-- 削除は hidden=1（行は残す。消した key は作り直せない）。初期の6問は origin='seed'
CREATE TABLE IF NOT EXISTS question_library (
    key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    answer_type TEXT NOT NULL CHECK (answer_type IN ('three_level', 'temperature')),
    origin TEXT NOT NULL CHECK (origin IN ('seed', 'doctor', 'adopted')),
    hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    created_at TEXT NOT NULL
);

-- D4 レジメンの下書き（v1.1。spec 9.1・architecture 9c）。院内だけ。
-- regimen は識別名（例: FOLFIRI-BV）。新規の下書きは識別名が決まるまで NULL。
-- base_version は既存の版から作った下書きの元の版（新規は NULL。採用で版1）。
-- 状態 open → working（Claude の1往復の間）→ open。adopted・discarded で閉じる。
-- generation は往復ごとに上がる（結果は世代が同じときだけ反映する。T94）。
-- chat_json は会話の文面（院内の画面だけに出す。採用・破棄で '[]' にする）
CREATE TABLE IF NOT EXISTS regimen_drafts (
    id INTEGER PRIMARY KEY,
    regimen TEXT,
    base_version INTEGER CHECK (base_version IS NULL OR base_version >= 1),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'working', 'adopted', 'discarded')),
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    form_json TEXT NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '{}',
    chat_json TEXT NOT NULL DEFAULT '[]',
    adopted_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    working_since TEXT,
    closed_at TEXT,
    CHECK ((status = 'working') = (working_since IS NOT NULL))
);

-- 1つのレジメンに開いている（open・working）下書きは1つまで
CREATE UNIQUE INDEX IF NOT EXISTS idx_regimen_drafts_active
    ON regimen_drafts (regimen)
    WHERE regimen IS NOT NULL AND status IN ('open', 'working');

-- D4 で採用した版の form JSON（skill_versions と同じ版に結びつく）。FOLFOX/CAPOX@1 は
-- リポジトリの regimen_forms/*.json に持つのでここには無い
CREATE TABLE IF NOT EXISTS regimen_forms (
    skill_name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    form_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (skill_name, version),
    FOREIGN KEY (skill_name, version) REFERENCES skill_versions (skill_name, version)
);

-- 日付の印（plan-device-records §4.4）。その日に記録があったことだけ。中身・種類は持たない。
-- 書いた人に通知を送らないために使う
CREATE TABLE IF NOT EXISTS record_marks (
    patient_id TEXT NOT NULL REFERENCES patients (id),
    record_date TEXT NOT NULL,
    last_marked_at TEXT NOT NULL,
    PRIMARY KEY (patient_id, record_date)
);

CREATE INDEX IF NOT EXISTS idx_record_marks_date ON record_marks (record_date);

-- 通知の登録（§4.3）。端末（endpoint）ごとに1行。notify_time は JST の HH:MM（30 分刻み）。
-- last_sent_date で1日1回に抑える
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id),
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    notify_time TEXT NOT NULL DEFAULT '20:00',
    last_sent_date TEXT,
    created_at TEXT NOT NULL
);

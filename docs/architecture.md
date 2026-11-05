# 実装の契約（architecture）

- 対象: `docs/spec.md` v1.0 の実装。並列に作業する実装エージェントは**全員この文書に従う**
- 共通の型は `backend/tsutae/schemas.py`（pydantic）。モジュール間の受け渡しは必ずこの型で行う
- **症例は全て合成**。実在の人名・病院名・電話番号を書かない（伏せ字のテスト用の人名・病院名も架空にする）

## 0. 実装エージェントの約束

1. **あなたが実装者です。他のエージェントに委譲しない**（グローバル CLAUDE.md の「オーケストレーター」はメインセッションのこと）
2. `pip install` / `npm install` / `uv` / `git`（commit・checkout・stash 等すべて）を実行しない。依存は入っている
3. Anthropic API を呼ばない（`claude` CLI・`claude_agent_sdk.query` を実際に動かさない）。API を呼ぶテストは `@pytest.mark.api` を付ける（キーが無ければ skip される）
4. **自分の担当ファイルだけ**を作る・直す。他のエージェントが同時に別ファイルを書いている。テストは自分のテストファイルだけ走らせる: `scripts/test.sh backend/tests/test_xxx.py`
5. 共有ファイルを編集しない: `pyproject.toml` `backend/pytest.ini` `backend/tests/conftest.py` `backend/tsutae/__init__.py` `backend/tsutae/config.py` `backend/tsutae/schemas.py` `backend/tsutae/patient_strings.json` `frontend/package.json` `scripts/*.sh` `Makefile` `docs/*`。足りなければ最終報告に「契約への要望」として書く
6. TDD: テストを先に書き、落ちることを確かめてから実装する。Python は Black（88桁）・型ヒント・ruff。整形は `.venv/bin/black <ファイル>` と `.venv/bin/ruff check --fix <ファイル>`（自分のファイルだけ）
7. 引数を書き換えない（新しいオブジェクトを返す）。関数は約50行以内、ファイルは 200〜400 行目安（最大 800）
8. 外からの入力は検証する。SQL はプレースホルダのみ。HTML はエスケープ（Jinja2 autoescape）
9. リポジトリ直下の `.env` に触れない（読み取りはサンドボックスで拒否される）
10. 日付は全て Asia/Tokyo。`tsutae.config.today()` / `now()` / `to_jst_date()` を使い、`datetime.now()` を直接呼ばない

## 1. ディレクトリと担当

```
backend/
  pytest.ini                      # 共有
  tsutae/
    config.py schemas.py patient_strings.json   # 共有（オーケストレーター）
    db/        __init__.py schema.sql connection.py repo_*.py      # W1-db
    course.py                                                      # W1-course
    skills/    __init__.py loader.py                               # W1-skills
    masking/   __init__.py replace.py detect.py surnames.txt allow_words.txt   # W1-masking
    data/      ctcae_terms.json                                    # W1-synthetic
    synthetic.py                                                   # W1-synthetic
    pipeline/  ...（W2）   report/ ...（W2）   eval/ ...（W2）
    api/       ...（W3）
  skills_home/.claude/skills/
    regimen-folfox/SKILL.md regimen-capox/SKILL.md report-format-default/SKILL.md  # W1-skills
  tests/       test_<module>_*.py（各担当）
data/synthetic/  demo_patient.json eval_patient_a.json eval_patient_b.json
                 labels_demo_patient.json labels_eval_patient_a.json labels_eval_patient_b.json  # W1-synthetic
frontend/        # W1-frontend（骨組み）→ W4（画面）
scripts/         smoke_agent_sdk.py（済）、seed_demo.py（W3）
```

- **Skill の置き場所は `backend/skills_home/.claude/skills/`**（spec の `.claude/skills/` から変更。`docs/decisions.md`）。Agent SDK は `cwd=backend/skills_home`, `setting_sources=["project"]` で読む

## 2. データモデル（SQLite、`db/schema.sql`）

日時は ISO 8601 文字列（`+09:00` 付き）、日付は `YYYY-MM-DD`。`PRAGMA foreign_keys=ON`。

| 表 | 列 |
|---|---|
| patients | id TEXT PK（仮名ID。`P-` + 英大文字数字8桁、`secrets` で生成）, regimen TEXT（v1.0 は CHECK(FOLFOX/CAPOX)。v1.1 で外す。API の入口で `list_regimens` と照合）, created_at |
| courses | id INTEGER PK, patient_id FK, course_no INT, infusion_date, planned_date NULL, next_visit NULL, note NULL, UNIQUE(patient_id, course_no) |
| entries | id INTEGER PK, patient_id FK, recorded_at, record_date（recorded_at の JST 日付）, kind CHECK(too_sick/answers/free_text/mixed), by_proxy INT, skill_version TEXT（例 `regimen-folfox@1`） |
| closed_answers | entry_id FK ON DELETE CASCADE, question_key, value CHECK(none/present/hard/not_measured/measured), temperature REAL NULL, PK(entry_id, question_key), CHECK((value='measured') = (temperature IS NOT NULL)) |
| free_texts | entry_id PK FK ON DELETE CASCADE, text TEXT NOT NULL（原文。Claude には送らない。送るのは伏せ字後） |
| visits | id INTEGER PK, patient_id FK, reception_no TEXT NULL（印刷済み・期限切れで NULL にする）, visit_date, created_at, status CHECK(generating/ready/printed/failed), expires_at, fallback INT DEFAULT 0, course_no INT NULL |
| timelines | visit_id PK FK ON DELETE CASCADE, json TEXT（`Timeline`） |
| reports | visit_id PK FK ON DELETE CASCADE, html TEXT, data_json TEXT（`ReportData`） |
| doctor_masks | visit_id FK ON DELETE CASCADE, entry_id FK ON DELETE CASCADE, spans_json TEXT（原文の伏せる区間 `[[start, end], …]`）, confirmed_clear INT CHECK(0/1), allowed_json TEXT（確かめた時に許す区間。伏せた後の文の位置）, created_at, PK(visit_id, entry_id) — D6 の医師の伏せ字。**位置と真偽だけで文面は入れない**。印刷済み・期限切れで reports と一緒に消す（2026-11-04 夜） |
| pipeline_logs | id PK, run_kind CHECK(visit/skill_change/regimen_chat。regimen_chat は v1.1), run_id INT, ts, event TEXT, hook_name NULL, agent_type NULL, tool_name NULL, decision NULL, duration_ms NULL, tokens_in NULL, tokens_out NULL, cost_usd NULL — **文面は入れない** |
| skill_changes | id PK, skill_name, requested_text, diff TEXT NULL, new_text TEXT NULL, base_version INT, new_version INT NULL, status CHECK(pending/approved/rejected/failed), error_code TEXT NULL, created_at, decided_at NULL |
| skill_versions | skill_name, version INT, content TEXT（SKILL.md 全文）, questions_json TEXT NULL（regimen のみ）, approved_at, PK(skill_name, version) |
| regimen_forms（v1.1） | skill_name, version INT, form_json TEXT（正規化した `RegimenForm`）, created_at, PK(skill_name, version), FK(skill_name, version) → skill_versions — D4 で採用した版のフォーム（採用と同じトランザクション）。FOLFOX/CAPOX@1 はリポジトリの `regimen_forms/*.json` |
| regimen_drafts（v1.1） | id PK, regimen TEXT NULL（識別名。新規は決まるまで NULL）, base_version INT NULL（新規は NULL）, status CHECK(open/working/adopted/discarded), generation INT, form_json, sources_json, chat_json（院内だけ。採用・破棄で `[]`）, adopted_version NULL, created_at, updated_at, working_since NULL（CHECK: working のときだけ）, closed_at NULL。部分 UNIQUE(regimen) WHERE open/working（1レジメンに開いた下書きは1つ） |
| question_library（v1.1） | key TEXT PK, label, text, answer_type CHECK(three_level/temperature), origin CHECK(seed/doctor/adopted), hidden INT, created_at |
| entries.client_entry_id | 受付で受け取った記録の端末の ID。`(patient_id, client_entry_id)` の部分一意索引（NULL の既存の行は対象外）。`migrate_db` が前の DB に足す（§12） |
| record_marks（通知） | patient_id FK, record_date, last_marked_at, PK(patient_id, record_date) — 記録があった日付の印。**中身・種類・代理の別を持たない** |
| push_subscriptions（通知） | id INTEGER PK, patient_id FK, endpoint TEXT UNIQUE, p256dh, auth, notify_time TEXT DEFAULT '20:00'（JST の HH:MM）, last_sent_date NULL, created_at |
| push_removed_sends（通知） | patient_id PK FK, last_sent_date — 消した登録の送信日（患者ごとに最後の日付だけ）。新しい行が引き継ぐので、オフにしてオンにしても1日1回まで |
| push_gone_endpoints（通知） | endpoint PK, gone_at — 送信先が 404・410 を返した endpoint。PUT で断る（410）。30 日で忘れる |

`skill_versions` は「その日の記録に使った質問集」を後から引くためのスナップショット（未設問「−−」の表示に使う）。起動時に現在の SKILL.md が未登録なら登録する。

### W1-db の公開関数（`tsutae.db`）
- 接続はリクエスト（またはバックグラウンドでの1回の生成）ごとに開く。WAL モード
- `connect(path: Path) -> sqlite3.Connection`（row_factory=Row、foreign_keys ON、`check_same_thread=False`）、`init_db(conn)`（schema.sql を流す。何度呼んでもよい）
- 患者: `create_patient(conn, regimen, patient_id=None) -> str`, `get_patient(conn, pid) -> dict | None`, `list_patients(conn) -> list[dict]`
- コース: `upsert_course(conn, course: Course) -> Course`, `list_courses(conn, pid) -> list[Course]`（course_no 昇順）
- 記録: `add_entry(conn, pid, entry: EntryCreate, recorded_at: datetime, skill_version: str) -> Entry`, `list_entries(conn, pid, start: date | None = None, end: date | None = None) -> list[Entry]`（recorded_at 昇順）, `get_entry(conn, entry_id) -> Entry | None`
- 受診: `create_visit(conn, pid, reception_no, visit_date, expires_at, course_no) -> int`, `get_visit(conn, vid) -> dict | None`, `list_visits(conn, statuses: tuple[str, ...] | None = None) -> list[dict]`, `set_visit_status(conn, vid, status, fallback: bool | None = None)`, `save_timeline(conn, vid, timeline: Timeline)`, `get_timeline(conn, vid) -> Timeline | None`, `save_report(conn, vid, html, data: ReportData)`, `get_report(conn, vid) -> tuple[str, ReportData] | None`, `mark_printed(conn, vid)`（reports・timelines を削除し reception_no を NULL、status=printed。printed への変更はこの関数だけで、`set_visit_status` は printed を受け付けない。印刷済みの受診への `save_*` は `VisitClosedError`）, `purge_expired(conn, now: datetime) -> int`（expires_at を過ぎた未印刷の受診に同じ削除をして件数を返す）
- ログ: `add_pipeline_log(conn, run_kind, run_id, event, **fields) -> None`, `list_pipeline_logs(conn, run_kind, run_id) -> list[dict]`
- Skill: `create_skill_change(...) -> int`, `get_skill_change`, `list_skill_changes`, `update_skill_change(conn, id, **fields)`, `save_skill_version(conn, skill_name, version, content, questions: list[Question] | None)`, `get_skill_version(conn, skill_name, version) -> dict | None`, `latest_skill_version(conn, skill_name) -> dict | None`
- 移行（v1.1、`migrate`）: `migrate_db(conn, migrations=MIGRATIONS) -> list[str]`（`init_db` が schema.sql の前に呼ぶ。`TableMigration(table, is_outdated, create_sql, copy_sql=None)` の一覧。古い CHECK の表だけ 12-step で作り直す）
- 下書き（v1.1、`repo_regimen_drafts`）: `create_draft`・`get_draft`・`find_active_draft`・`list_active_drafts`・`update_draft_form`（open だけ）・`begin_working`（generation+1）・`recover_stale_working(conn, *, timeout_s)`・`discard_draft`。採用の行は `insert_skill_version_row`・`insert_regimen_form_row`・`mark_adopted_row`（トランザクションは呼び出し側）
- 部品集（v1.1、`repo_question_library`）: `seed_question_library(conn) -> int`（初期の6問。起動時に呼ぶ。何度でもよい）, `list_library_questions(conn, *, include_hidden=False) -> list[dict]`, `get_library_question(conn, key) -> dict | None`, `add_library_question(conn, *, key, label, text, answer_type="three_level", origin="doctor"|"adopted") -> dict`（形・H1 は `QuestionInputError(code, field)`、重複は `QuestionConflictError("key_taken")`）, `hide_library_question(conn, key) -> dict`（hidden=1。初期の6問は `seed_question`、版が使う key は `in_use`）。採用の中で入れるときは `insert_question_row(conn, item, origin, skip_existing=True)`（トランザクションは呼び出し側）

## 3. コースと Day（W1-course、`tsutae.course`、純関数）
- Day1 = 実投与日。次コースの実投与日の前日までが今コース。次コースが未登録なら `infusion_date + cycle_days - 1` まで（それ以降の記録は、次コース登録まで今コースの Day15, 16… として数える）
- `build_schedule(courses: list[Course], course_no: int, cycle_days: int, pump_removal_day: int | None) -> CourseSchedule`
- `day_of(d: date, schedule: CourseSchedule, *, courses: Sequence[Course]) -> int | None`（Day1 より前は None。次コース開始日以降も None。courses は schedule を作ったのと同じもの）
- `validate_courses(courses) -> list[Course]`（course_no 順に並べて返す。course_no の重複・実投与日の逆転などの矛盾は `CourseValidationError(code)`（ValueError）。どの関数も矛盾した courses にはこの例外を出す。医師 API の実投与日登録は保存前にこれを呼び、失敗は 400 `{"error": code}`）
- `course_for_date(courses, d) -> Course | None`、`current_course(courses, today) -> Course | None`（実投与日が today 以前で最大の course_no）、`previous_course(courses, course_no) -> Course | None`
- `grid_days(schedule, until: date | None = None) -> list[int]`（今コース: Day1〜max(last_day_date の Day, until の Day)。前コース（until なし）: Day1〜last_day_date の Day）
- `delay_note(schedule) -> str | None` → `"延期（予定より2日）"`。延期の理由は書かない

## 4. Skill（W1-skills、`tsutae.skills`）
SKILL.md = YAML frontmatter（機械が読む。`RegimenSkill` / `ReportFormatSkill` に一致）＋本文（自然言語。Agent SDK の主エージェントが読む）。

```yaml
---
name: regimen-folfox
description: FOLFOX の投与スケジュール・クローズ質問集・固定規則。記録の変換時に使う
version: 1
regimen: FOLFOX
cycle_days: 14
pump_removal_day: 3
questions:
  - {key: numbness, text: 手足のしびれや冷たいものがさわりにくい感じはありましたか, answer_type: three_level}
  - {key: diarrhea, text: 下痢はありましたか, answer_type: three_level}
  - {key: stomatitis, text: 口の中の痛みや口内炎はありましたか, answer_type: three_level}
  - {key: nausea_appetite, text: 吐き気や食欲の落ち込みはありましたか, answer_type: three_level}
  - {key: fever, text: 熱を測りましたか, answer_type: temperature}
fixed_rules:
  - {key: fever_38, question_key: fever, threshold_celsius: 38.0, patient_string_key: fixed_rule.fever_38}
---
```
- `parse_skill_md(text) -> tuple[dict, str]`（frontmatter と本文。壊れていれば `SkillFormatError`）
- `validate_skill_text(skill_name: str, text: str) -> RegimenSkill | ReportFormatSkill`（名前の接頭辞で型を選ぶ。frontmatter の name とディレクトリ名の一致も検査。失敗は `SkillValidationError(code: str)`）
- `load_skill(skill_name, skills_dir: Path | None = None)`, `load_regimen_skill(regimen, skills_dir=None) -> RegimenSkill`（v1.0 は FOLFOX→regimen-folfox, CAPOX→regimen-capox の固定。v1.1 は `regimen-` + 識別名の小文字の規則で引き、Skill 名と frontmatter の regimen の一致もこの規則で検査する）, `load_report_skill(name="report-format-default", skills_dir=None) -> ReportFormatSkill`, `read_skill_text(skill_name, skills_dir=None) -> str`, `skill_path(skill_name, skills_dir=None) -> Path`
- `SKILL_NAME_PATTERN = r"^(regimen|report-format)-[a-z0-9-]+$"`（H3 の書き込み先検査にも使う）
- CAPOX: cycle_days 21、pump_removal_day なし、手足症候群（`hand_foot`）を追加

## 5. 伏せ字（W1-masking、`tsutae.masking`）
二段。**一次（置換）と二次（検出）は別の規則にする**（同じだと二次が永遠に発火しない）。

- 一次 `mask_text(text: str) -> MaskResult(masked: str, counts: dict[str, int])`
  - 姓辞書（`surnames.txt`、架空でなく一般的な日本の姓 300 語程度）＋敬称（さん/先生/くん/ちゃん/様）→「○○さん」「○○先生」…（敬称は残す）
  - 電話（`0\d{1,4}-?\d{1,4}-?\d{3,4}` 等）・メール・住所（都道府県＋市区町村＋番地）→「[伏せ字]」
  - 「病院／医院／クリニック／医療センター」で終わる語 →「[病院]」
  - 残す: 日付・時刻・体温・「東京へ行った」程度の地域名・「お母さん」等の続柄
- 二次 `detect_identifiers(text: str) -> list[Detection(rule: str, start: int, end: int)]`（一次の**後の**文に掛ける。一次より厳しい）
  - `unknown_before_honorific`: 敬称の直前の語（漢字・カタカナ・ひらがな2字以上）で、「○○」でも続柄・職種の許可語（`allow_words.txt`: お母さん、娘さん、看護師さん、薬剤師さん、皆さん 等）でもないもの
  - `long_digits`: 7桁以上の数字列（区切り記号を除いて数える。体温・日付は対象外）
  - `at_mark`: `@` または全角 `＠`
  - `before_facility`: 「病院／医院／クリニック／センター」の直前の語で「[病院]」になっていないもの
- `check_text(text) -> MaskCheck(masked: str, detections: list[Detection])`（一次→二次をまとめて）
- 該当した記録は、その記録だけ Claude への送信対象から外す（`UnprocessedEntry(reason=<規則名>)`）。原文は院内画面 D6 だけに出す

**W2b の決定（2026-11-03、上より優先）**
- 敬称は さん・先生・せんせい・くん・君・ちゃん・様・さま・氏・殿（一次・二次とも）
- `normalize_text(text) -> str`: 改行（CRLF・CR・U+2028・U+2029）を `\n` に、タブを空白に、それ以外の制御文字（Cc）と書式文字（Cf: U+200B・U+00AD・U+FEFF・U+2060 等）を削除する。`check_text` は最初にこれを掛け、`masked` は正規化後の文から作る。**改行は残す**（引用は改行を含みうる）。規則は改行・空白をまたいで働く（「磯鷲\n南さん」「架空 病院」）が、形容詞・副詞・助詞の後の改行（「だるい\n医院へ」）では検出しない
- 一次は仮名ID（`P-[A-Z0-9]{8}`、大文字小文字・全角を問わない）を「[ID]」に置き換える
- 二次の規則は `unknown_before_honorific` `long_digits` `at_mark` `before_facility` `address_number`（番地・N-N-N の住所）`id_like`（英字1〜2字＋ハイフン類＋英数字3字以上。例 A-023・P-DEMO0001 の取り残し）
- `detect_identifiers(text)` は**依頼文全体**（H1・convert②）用: JSON の文字列エスケープ（`\n` `\t` `\r` `\"` `\\` `\uXXXX`）を同じ長さの空白とみなして検出し、`"regimen_skill_version"`・`"report_skill_version"`・`"skill_version"` キーの値の `@` だけを数えない。`detect_in_patient_text(text)` は患者の文用で例外なし。`check_text` は後者を使う

## 6. 合成データ（W1-synthetic）
- `data/synthetic/*.json` は `SyntheticPatient`、`labels_*.json` は `PatientLabels`（schemas.py）。`tsutae.synthetic` に `load_patient(path)`, `load_labels(path)`, `all_patients()`, `hard_case_counts(labels) -> dict[str, int]`, `validate_dataset() -> list[str]`（問題の一覧。空なら OK）
- デモ患者 `demo_patient.json`（`patient_id: "P-DEMO0001"`, `visit_date: 2026-11-09`, 受付番号 `"A-023"`）:
  - C1 実投与 2026-09-27 ／ C2 予定 2026-10-11・実投与 2026-10-13（延期2日）／ C3 実投与 2026-10-27 → 受診日 11/09 は C3 Day14
  - 毎コース Day3〜5 に「つらくて書けない」、C3 Day5 に下痢の食い違い（クローズ「なし」＋自由記載に下痢）、C3 Day8 に 37.9℃、代理入力1日、回想1件、入力なしの日が数日
  - 一次置換で伏せられる人名・病院名を含む記載が数件、**二次検出に掛かる記載が1件**（辞書にない架空の姓＋さん。D6 デモ用、`expect_unprocessed: true`）
- 評価用 `eval_patient_a.json` / `eval_patient_b.json`: 各2コース、デモとは別の人・別のパターン
- 自由記載は全体で約60件。**全ての自由記載に正解ラベル**（暦日・Day・用語・status・食い違い・引用）。難ケース4種（`contradiction` / `mild_improving` / `relative_time` / `negation`）をそれぞれ複数件。相対時間は「点滴の次の日から」「先週木曜まで」「ポンプを外した日」を必ず含む
- `source_quote` は**一次置換後**の自由記載に部分一致すること（テストで検査）
- 回想（recalled）は「出来事の暦日が記録日より前」なら true（相対時間で日付を戻した場合も含む）
- 用語は `backend/tsutae/data/ctcae_terms.json`: `[{"term": "下痢", "en": "Diarrhea", "question_key": "diarrhea"}, …]`（CTCAE v5.0 日本語訳 JCOG 版の有害事象名を約30語。出典「有害事象共通用語規準 v5.0 日本語訳JCOG版より引用」をファイル内 `source` に）。ラベルの term はこの一覧から選ぶ

## 7. 変換パイプライン（W2-pipeline、`tsutae.pipeline`）

T03 スモークの事実（`docs/decisions.md`）: H1 は `UserPromptSubmit` で止められる／サブエージェント内のツール呼び出しにも `PreToolUse` が掛かる（`agent_type` に定義名）／起動ツール名は init で `Task`、Hook で `Agent`／組み込みエージェント（general-purpose 等）と Bash・Write 等が既定で見える／`max_turns` 超過は `ResultError` 例外。

| ファイル | 中身 |
|---|---|
| `inputs.py` | `prepare_input(*, courses, entries, regimen_skill, report_skill, visit_date) -> PreparedInput`。今コース（`course.current_course(courses, visit_date)`）の Day1〜min(最終日, visit_date) の記録だけ。記録日時順に entry_no=1,2,… を振る。自由記載は `masking.check_text` に掛け、検出があればその**記録ごと**入力から外し `UnprocessedEntry(entry_id, reason=規則名)`。仮名ID・受付番号は入れない |
| `prompt.py` | `build_prompt(prepared) -> str`（主エージェントへの依頼文＋ `PipelineInput` の JSON）、`SYSTEM_PROMPT`。**依頼文に敬称（さん・先生 等）を書かない**（H1 が自分の依頼文に反応しないように。テストで `detect_identifiers(build_prompt(...)) == []` を確かめる） |
| `agents.py` | `build_agents(settings, regimen_skill_name) -> dict[str, AgentDefinition]`: `date-normalizer` / `term-mapper` / `contradiction-finder`。model=`settings.subagent_model`、`tools=[]`（ツールなし。JSON テキストを返す）、`skills=[regimen_skill_name]`。prompt は日本語で、出力 JSON の形を明示 |
| `tools.py` | `RunCollector`（1回の変換の受け皿。timeline と picks を保持）、`handle_emit_timeline(args, collector) -> dict`、`handle_emit_report(args, collector) -> dict`（pydantic で検証し、失敗は `{"content":[…], "is_error": True}` で理由を返してモデルに直させる）、`build_server(collector) -> McpSdkServerConfig`（名前 `tsutae`、ツール `emit_timeline` `emit_report`） |
| `hooks.py` | 下の表 |
| `logs.py` | `PipelineLogger(conn, run_kind, run_id)`: `event(name, **fields)` で `db.add_pipeline_log`。**文面（プロンプト・引用・理由の本文）は入れない**。理由は規則名などの短いコードだけ。テスト用に conn なしで記録だけ持つ `MemoryLogger` も置く |
| `runner.py` | `AgentRunner` プロトコル: `async run(prompt: str, options: ClaudeAgentOptions, collector: RunCollector) -> RunStats`。`SdkRunner` は `claude_agent_sdk.query` を回し ResultMessage から RunStats を作る。テスト用の `FakeRunner` は `backend/tests/` 側に置く（options.hooks の H1・H2・H4 を実際に呼び、collector 経由で handle_emit_* を呼ぶ） |
| `orchestrator.py` | `build_options(prepared, collector, logger, settings, skills_home) -> ClaudeAgentOptions`、`async convert(prepared, *, runner, logger, settings) -> ConversionResult` |
| `service.py` | 7d |

Hook（`hooks.py`）。意見のない Hook は `{}` を返す。全て `HookMatcher(on_failure="block")`。

| 関数 | イベント・matcher | 挙動 |
|---|---|---|
| `make_h1(logger)` | UserPromptSubmit | `detect_identifiers(prompt)` に掛かれば `{"decision":"block","reason":<規則名>,"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","suppressOriginalPrompt":True}}` |
| `make_h2(masked_texts, logger)` | PreToolUse `mcp__tsutae__emit_timeline\|mcp__tsutae__emit_report` | events の `source_quote`・contradictions の `free_text_quote`・per_symptom の `representative_quote` が、その entry_no の伏せ字後の文に部分一致しない、または entry_no が未知 → `permissionDecision: "deny"` と理由（どの項目かを番号で。原文は入れない） |
| `make_h3(skills_root, logger)` | PreToolUse `Write\|Edit\|MultiEdit` | `file_path` を `resolve()` してから、`skills_root/.claude/skills/<SKILL_NAME_PATTERN>/SKILL.md` でなければ deny |
| `make_h4(allowed_tools, allowed_subagents, logger)` | PreToolUse（matcher なし＝全ツール） | 許可外のツール、`Agent`/`Task` の `subagent_type` が許可外 → deny |
| `make_trace_hooks(logger)` | SubagentStart / SubagentStop / PostToolUse | 記録するだけ（D5 の可視化用） |
| `build_hooks(*, masked_texts, logger, allowed_tools, allowed_subagents)` | — | 上をまとめた `dict[str, list[HookMatcher]]` |

`convert` の手順: ①入力の記録が0件なら Claude を呼ばず空の Timeline（unprocessed だけ）で成功 ②コードで `detect_identifiers(prompt)` → 掛かれば `error_code="h1_blocked"` でフォールバック ③`asyncio.wait_for(runner.run(...), settings.pipeline_timeout_s)` ④`TimeoutError`→`timeout`、`ClaudeSDKError`（`ResultError` を含む）→ `sdk_error_code(exc)` で予算超過なら `max_budget`、max turns なら `max_turns`、他は `sdk_error`（D4 の書き換えも同じコード）、emit_timeline が来ない→`no_timeline` ⑤成功なら `ConversionResult(timeline（unprocessed を足す）, picks, fallback=False, stats)`。例外の本文はログに入れない（コードだけ）。

ClaudeAgentOptions の要点: `cwd=str(SKILLS_HOME)`, `setting_sources=["project"]`, `skills=[<regimen skill>, "report-format-default"]`, `model=settings.model`, `agents=build_agents(...)`, `mcp_servers={"tsutae": build_server(collector)}`, `allowed_tools=["Task", "Agent", "Skill", "mcp__tsutae__emit_timeline", "mcp__tsutae__emit_report"]`, `disallowed_tools=["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Workflow", "Read", "Glob", "Grep"]`, `permission_mode="dontAsk"`, `hooks=build_hooks(...)`, `max_turns=settings.pipeline_max_turns`, `max_budget_usd=settings.pipeline_max_budget_usd`, `system_prompt=SYSTEM_PROMPT`, `extra_args={"no-session-persistence": None}`, `env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}`（`NO_CLAUDE_MD_ENV`。`setting_sources=["project"]` は cwd の祖先の CLAUDE.md も読むため、リポジトリ直下の開発用 CLAUDE.md を変換に入れない。2026-11-04 追加）。

主エージェントの手順（SYSTEM_PROMPT と build_prompt に書く）: Skill（regimen と report-format）を読む → 3役を `Agent` ツールで呼ぶ（date-normalizer と contradiction-finder、その後 term-mapper。並行でよい）→ 結果をまとめ `emit_timeline`（events, contradictions）→ report-format に従い `emit_report`（per_symptom）。Grade・重さの語・助言・原因の推測を出さない。欠けた日を埋めない。食い違いを解決しない。

**W2b の決定（2026-11-03、上より優先）**
- `prepare_input(..., exclude_literals: Sequence[str] = ())`: 自由記載に `exclude_literals`（service が渡す仮名ID・受付番号。NFKC＋casefold で比べる、空文字は無視）を含む記録は外し `UnprocessedEntry(reason="known_identifier")`。自由記載の正規化は `masking.check_text` に任せる（pipeline 側で改行を空白にしない。`masked_texts` は改行を含みうる）
- 範囲外（今コースの Day1 より前・最終日より後・visit_date より後）の記録は**黙って外す**（`UnprocessedEntry` にしない。unprocessed は「伏せ字漏れの疑い・識別子を含む」の意味だけ）。件数はログに `out_of_range_count` で残す
- 自由記載の記録が1件も無い（`masked_texts` が空）なら Claude を呼ばず、空の Timeline（events・contradictions とも空、unprocessed だけ）で成功
- `emit_timeline` の検査: event の `date` はその記録の記録日以前。`day` は `course.day_of(date, schedule, courses=...)` と一致（None ならば None のみ）。同じ (entry_no, term, date, status, source_quote) の重複・同じ食い違いの重複は拒否
- `emit_report` の検査: 受け付けた timeline の present/improving の term ごとに per_symptom の行がちょうど1つ。行の欠け・余分・重複は拒否。**順序はサーバーが (start_date, term) で並べ直して受け付ける**（2026-11-04 変更。日本語の term 名の文字コード順はモデルが再現できない）。拒否の理由は番号・項目名と、写す項目・数える項目の**期待される値**を含める（自由記載の文面と用語名は含めない。ログは位置だけ）
- 依頼文に今コースの「日付と Day の対応表」（Day1〜最も遅い record_date）を入れ、モデルに Day を計算させない
- `convert` が想定外の例外で `internal_error` にするとき、例外の**型名だけ**をログ（`error_type`）に残す


## 7b. レポート（W2-report、`tsutae.report`）

| ファイル | 中身 |
|---|---|
| `build.py` | `build_report_data(*, reception_no, patient_id, regimen_skill, report_skill, courses, entries, visit_date, prepared, result: ConversionResult, questions_by_version: dict[str, list[Question]], record_marks: Sequence[RecordMark] = ()) -> ReportData`。**決定的**（同じ入力なら同じ出力）。下の規則 |
| `render.py` + `templates/report.html.j2` + `templates/report.css` | `render_report_html(data: ReportData, *, questions: list[Question]) -> str`。Jinja2（autoescape）。下の描画規則 |

組み立ての規則:
- header: 記録日数＝記録（too_sick を含む）のある日数、届いていない＝日付の印（`record_marks`）があって記録の無い日数、入力なし＝記録も印も無い日数、つらくて書けない＝too_sick の日数（今コースの Day1〜min(最終日, visit_date)）。延期注記は `course.delay_note`。`fallback` は `result.fallback`
- attention（この順）: 食い違い（timeline.contradictions）／`fever_attention_celsius` 以上の体温（今コース）／つらくて書けない（今コース。前コースの同じ Day も too_sick なら `previous_course_same_day=True`）／届いていない日（今コース。紙は `記録が届いていない日: Day5, Day6` の1行）／未処理の記録（count のみ）
- 届いていない日（plan-device-records §5.6）: 同じ日に記録が1件でもあれば届いた扱い（日付の単位）。経過表のセルは no_input（空白）のまま。`record_marks` は `prepare_input` に渡さないので Claude には送らない（テストで固定）。AI 変換なしでも出る
- grid: 今コースの行（質問ごと）＋体温行（`show_temperature_row`）＋ `show_previous_course` なら前コースの行（**クローズ回答のみ**、AI の結果を使わない）。セル state: その日の記録の回答＝none/present/hard、記録が無い＝no_input、その日の記録の skill_version の質問集にその質問が無い＝not_asked、too_sick だけの日＝too_sick。同じ日に複数の回答があれば重い方（hard > present > none）。free_text_mark は今コースの events（status が present か improving、question_key 一致、event の date のその Day）、recalled_mark はその event が recalled。列: by_proxy の記録がある日は「代」、too_sick の日は斜線
- per_symptom: `result.picks.per_symptom`（無ければ空）
- quotes: 伏せ字後の自由記載（`prepared.masked_texts`）を Day 順に、`quotes_max_items` まで。未処理の記録は載せない
- フォールバック（`result.timeline is None`）: free_text_mark なし・食い違いなし・per_symptom 空。経過表と引用は同じ

描画の規則: A4 一枚・モノクロ（`@page { size: A4; margin: 10mm }`、`@media print`）。セル: なし=薄い「−」、ある=網掛け、つらい=濃い網掛け、入力なし=空白、未設問=「−−」、つらくて書けない=列全体の斜線、○・「回」・列頭「代」、凡例を欄外に固定。冒頭に「症例は全て合成」、fallback なら「AI変換なし」。用語の欄外に「有害事象共通用語規準 v5.0 日本語訳JCOG版より引用」。low_confidence_threshold 未満の per_symptom は「？」。**Grade・軽症・中等症・重症・重篤などの語を出さない**（テストで検査）。引用が多く溢れる場合は引用欄を2枚目に回す（`page-break-before`）。届いていない日の行が折り返す分も見積もりに入れる

## 7c. 評価（W2-eval、`tsutae.eval`）

| ファイル | 中身 |
|---|---|
| `metrics.py` | 純関数。`evaluate(predicted: Timeline, prepared: PreparedInput, labels: list[EntryLabel]) -> EvalResult`（EvalResult は eval 内で定義）。entry_no ↔ entry_seq は `prepared.entry_ids`（合成データでは entries.id = seq）。①日付正規化の一致率（ラベルの event ごとに同じ記録・同じ term（無ければ同じ question_key）の予測を対応づけ、date と day の一致率）②用語の一致率（同じ記録に同じ term の予測があるか）③食い違いの再現率・適合率（(記録, question_key) で対応）④「軽い・改善中を absent と誤る／取りこぼす」件数と「否定を present/improving とした」件数 ⑤引用一致率（予測の source_quote が伏せ字後の文に部分一致する割合）。失敗例の一覧（記録・項目・期待・予測）を返す。expect_unprocessed の記録と、今回の入力に入っていない記録は除外 |
| `run.py` | `python -m tsutae.eval.run [--cache-only RUN_DIR] [--patients ...]`。role=eval の患者の**各コース**について visit_date=そのコースの最終日で `prepare_input` → `convert(SdkRunner)` → 予測を `docs/eval/runs/<日時>/<patient>_c<n>.json` に保存 → metrics → `docs/eval/<日付>.md`（5指標の実測値・失敗例・モデル名・所要時間・費用）。`--cache-only` は保存済みの予測から metrics と md だけ作り直す（API を呼ばない）。`.env` は `config.load_env_file()` で読む |
| synthetic 連携 | `tsutae.dataset`（共有・済）: `to_entries(patient) -> list[Entry]`（id=seq）、`to_courses(patient) -> list[Course]`、`to_entry_create(src) -> EntryCreate`。評価・テスト・デモ投入はこれを使う |

## 7d. 受診時の生成（W2-service、`tsutae.pipeline.service`）
- `async generate_visit_report(conn, visit_id, *, runner, settings, logger=None) -> None`: visits から患者・visit_date を読み、courses・entries・Skill（`skill_versions` から版ごとの質問集）を集め、`prepare_input` → `convert` → `build_report_data` → `render_report_html` → `save_timeline`（timeline が None でも unprocessed だけの Timeline を保存）・`save_report`・`set_visit_status(ready, fallback=…)`。途中で例外が出てもフォールバックのレポートを作って ready にし、それも失敗したら failed。受付番号は Claude に送らない
- `ensure_skill_versions(conn, skills_dir) -> None`: 現在の SKILL.md が `skill_versions` に無ければ登録する（起動時・合成データ投入時に呼ぶ）
- `questions_by_version(conn) -> dict[str, list[Question]]`（`"regimen-folfox@1"` → 質問集）

## 8. API（W3、FastAPI。フロントはこの形で作る）
共通: JSON。エラーは `{"error": "<code>"}`（文面ではなくコード。患者画面はコードから `patient_strings.json` のキーを選ぶ）。

### 患者（Cookie `tsutae_pid`）
| メソッド・経路 | 入力 | 出力 |
|---|---|---|
| `POST /api/patient/register` | `{pid}` | `{ok: true}` + Cookie。未知の pid は 404 `{"error":"unknown_patient"}` |
| `GET /api/patient/strings` | — | `patient_strings.json` そのもの |
| `GET /api/patient/{pid}/questions` | — | `{skill_version, questions: Question[], fixed_rules: [{question_key, threshold_celsius, patient_string_key}], today}`（`today` はサーバーの今日 `YYYY-MM-DD`（JST。`config.today()`）。今日の記録の見出しの日付に使い、端末の時計は使わない。`fixed_rules` は画面のコードで比べる規則で、体温はサーバーに送らない） |
| `POST /api/visit` | `{reception_no, entries?}`（Cookie で患者識別。`entries` は §12） | `{ok: true, message_key: "visit.done"}`。変換はバックグラウンド |

記録の経路（`POST`・`GET /{pid}/entries`、`POST /{pid}/entries/{id}/undo`）は外した。記録はスマホに置く（§12）。

- Cookie の pid と経路の `{pid}` が違えば 403。患者 API のモジュールは `reports`・`timelines`・pipeline を import しない（アーキテクチャテスト）
- 患者画面に出る文字列は `patient_strings.json` と、医師が承認した Skill の質問文だけ

### 医師（Cookie `tsutae_doctor`。`POST /api/doctor/login {password}` で発行、`DOCTOR_PASSWORD` と照合）
| メソッド・経路 | 出力 |
|---|---|
| `POST /api/doctor/login` / `POST /api/doctor/logout` | `{ok}` |
| `GET /api/doctor/patients` | `{patients: [{id, regimen, created_at, register_url}]}` |
| `POST /api/doctor/patients {regimen}` | `{id, register_url}`（register_url = `{public_base_url}/register?pid=<id>`、登録用 QR はフロントで描く。QR はアプリを入れる入口で、受診の受付には使わない。受付は受診タブ `/visit`） |
| `GET /api/doctor/patients/{pid}/courses` / `POST /api/doctor/courses`（`Course`） | `{courses: Course[]}` / `Course` |
| `GET /api/doctor/visits` | `{visits: [{id, reception_no, patient_id, status, fallback, created_at, expires_at, unprocessed_count}]}` |
| `GET /api/doctor/visits/{id}/report` | `text/html`（A4 印刷用） |
| `POST /api/doctor/visits/{id}/printed` | `{ok}`（レポート・変換結果・受付番号を削除） |
| `GET /api/doctor/visits/{id}/unprocessed` | `{entries: [{entry_id, record_date, reason, text}]}`（D6。原文。紙には載せない） |
| `GET /api/doctor/pipeline/{visit_id}/events` | `{status, events: [{ts, event, hook_name, agent_type, tool_name, decision, duration_ms}]}`（D5。ポーリング） |
| `GET /api/doctor/skills` | `{skills: [{name, version}]}` |
| `POST /api/doctor/skill-changes {skill_name, request_text}` | `{id, status, diff}`（pending） |
| `GET /api/doctor/skill-changes` | 一覧 |
| `POST /api/doctor/skill-changes/{id}/approve` / `/reject` | `{ok, new_version?}` |
| `GET /api/doctor/regimen-drug-names`（v1.1） | `{names: [薬の名前]}`（`tsutae.regimen.drug_names`。`GET /regimens` と同じレジメンの今の版の form の薬 → 固定の5つの順で重複なし。form の無い版は飛ばし、読めない form は警告して飛ばす） |
| `POST /api/doctor/regimen-drafts {from:"new"}｜{skill}` / `GET …` / `GET …/{id}` / `PATCH …/{id}/fields {changes:[{field_id,value}], adds:[{section,row_id}], deletes:["drugs.<row_id>"]}` / `POST …/{id}/discard`（v1.1、T93） | `{draft, created}`（既存のレジメンに開いた下書きがあればそれ） / `{drafts: [要約]}` / `{draft}`（form は prose を除く・sources・chat・missing・schedule_locked） / `{draft}`（検査は 422 `{error:"invalid_fields", issues:[{field_id,code,message}]}`。読んでから書くまでに別の書き手が変えたら 409 conflict） / `{ok}`。working の間は 409 working |
| `GET /api/doctor/regimen-drafts/{id}/preview` / `POST …/{id}/adopt {confirm_token, ai_values_confirmed}`（v1.1、T93） | `{ai_values, skill_md:{kind:full｜diff,text}｜null, patient_preview, issues, confirm_token, version, …}` / `{ok, skill_name, version, regimen}`（409 token_mismatch・ai_values_unconfirmed・stale・schedule_locked・code_taken・not_open・busy、422 invalid_form） |
| `POST /api/doctor/regimen-drafts/{id}/turns {text}`（v1.1、T94。Claude の1往復。応答まで待つ。上限 `regimen_turn_timeout_s`） | `{draft, turn_error}`（turn_error は成功なら null。timeout・max_turns・max_budget・sdk_error・internal_error・code_taken・invalid_result は open に戻して会話に失敗の行、遅れた結果を捨てたら discarded）。入力の文・依頼文に H1 は 422 `{error:h1_blocked, issues:[{field_id: text（先生の文）か prompt（依頼文の他の部分）, code: identifier, message: 規則の名前}]}`（Claude を呼ばず保存しない。文面は返さない）、working の間は 409 working、読んでから始めるまでに PATCH が入れば 409 conflict、閉じた下書きは 409 not_open |
| `GET /api/doctor/question-library` / `POST … {key, label, text, answer_type?}` / `DELETE …/{key}`（v1.1） | `{questions: [{key, label, text, answer_type, origin}]}`（外した問は除く） / `{question}`（形・H1 は 422 `{error, field}`、重複は 409 key_taken。3択だけ） / `{ok}`（外すだけ。初期の6問は 409 seed_question、版が使う key は 409 in_use） |

### W2b 後の決定（2026-11-04）
- masking の `Detection`・`MaskResult`・`MaskCheck` は masking の中の dataclass のままでよい（§0「共通の型は schemas.py」の例外。masking の外へは `check_text` の結果として渡すだけ）
- ログの `out_of_range_count`・`error_type` は `pipeline_logs.decision` に `key:value` の形で入れる（列は足さない）。`ConversionResult.error_code` には `skill_version_mismatch`・`skill_load_error` もある（convert は実行直前に Skill の版を照合する）
- `exclude_literals` の照合は NFKC → ハイフン類を `-` → 空白・制御・書式を除く → casefold の部分一致。短い受付番号（数字2字など）で誤って外れても、D6 に回るだけなので受け入れる
- `db.set_visit_status` は印刷済み・期限切れの受診を変えない（条件付き UPDATE。0 行なら `VisitClosedError`）
- 依頼文は `json.dumps(..., ensure_ascii=False)` で作る（`detect_identifiers` の `\uXXXX` の扱いの前提）

### 8b. W3 の実装の形（2026-11-03 決定）
| ファイル | 担当 | 中身 |
|---|---|---|
| `api/app.py` | W3-api | `create_app(settings: Settings \| None = None, *, runner_factory=None, skill_editor=None) -> FastAPI`。`app.state` に settings・runner_factory（既定は `SdkRunner`）・skill_editor（既定は `SdkSkillEditor`）。起動時に `init_db`・`ensure_skill_versions`・`purge_expired`。`backend/tsutae/api/__main__.py` は不要（`uvicorn tsutae.api.app:app`、`app = create_app()` は遅延でよい） |
| `api/deps.py` | W3-api | 接続はリクエストごと（`Depends` で開いて閉じる）。患者 Cookie `tsutae_pid`（値は `pid + "." + base64url(HMAC-SHA256(secret_key, "patient:" + pid))`。2026-11-04 変更。署名が無い・違えば 401。登録 API はクライアントごとに失敗10回/10分を超えると 429 `too_many_attempts`）、医師 Cookie `tsutae_doctor`（値は発行時刻＋HMAC-SHA256(secret_key)。12時間で失効。標準ライブラリの `hmac` で作る）。どちらも HttpOnly・SameSite=Lax。エラーは `{"error": code}`（401 `not_logged_in`・403 `forbidden`・404 `not_found`・422 `invalid_input`）。`RequestValidationError` も `{"error":"invalid_input"}` に変える（入力の文面を返さない。自由記載が長すぎるときだけ `free_text_too_long`。2026-11-04） |
| `api/patient.py` | W3-api | §8 の患者 API。**`tsutae.pipeline`・`tsutae.report`・`get_timeline`・`get_report` を import しない**。質問集は `skills.load_regimen_skill`。記録の本文を受ける経路は無い（§12）。38.0℃ の案内は画面のコード（§13 の `patient/fixedRules.ts`）が出し、`api/fixed_rules.py` の純関数 `notices_for(entry: EntryCreate, skill: RegimenSkill) -> list[str]`（体温 ≥ threshold で `patient_string_key`。コードの比較だけ）は同じ表で確かめる Python の側の判定 |
| `api/visit.py` | W3-api | `POST /api/visit`: Cookie の患者で visit を作る（`expires_at = now + report_ttl_hours`、course_no は今コース、status=generating）→ `BackgroundTasks` で新しい接続を開き `generate_visit_report` を呼ぶ。受付番号は NFKC → 前後の空白除去だけで正規化し 1〜32 字で、制御文字・書式文字（Cc・Cf）を含むものは断る（大文字化・ハイフンの統一はしない。画面の `normalizeReceptionNo` と同じ表 `frontend/src/test/fixtures/reception_no_cases.json` で確かめる）。approve の応答 `new_version` は必須（reject は `{ok: true}` のみ）。本文の `entries` の検査と保存は §12。自由記載の長さは端末が保存の前に確かめる（`today.free_text_too_long`）。今コースが無ければ 409 `{"error":"no_course"}` |
| `api/doctor.py` | W3-doctor | §8 の医師 API（skill-changes 以外）。`GET /visits` と `GET /visits/{id}/report` の前に `purge_expired`。レポートは `HTMLResponse` に `Cache-Control: no-store` と `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:`。`POST /courses` は保存前に `validate_courses`（既存＋新規）。events は `{status, events}`（ポーリング） |
| `api/doctor_skills.py` | W3-doctor | `GET /api/doctor/skills`・`POST/GET /api/doctor/skill-changes`・approve・reject。`tsutae.skillchange` を呼ぶ |
| `skillchange/`（`editor.py` `service.py` `diff.py`） | W3-skillchange | 下の 9b |
| `scripts/seed_demo.py` | W3-api | `python scripts/seed_demo.py [--db PATH]`: 合成3人（`tsutae.dataset`）とコース・記録を入れ、`ensure_skill_versions`。既にいる患者は飛ばす（**DB を消さない**） |
| `api/patient_push.py` `push/*.py` `db/repo_push.py` `db/repo_record_marks.py` | 通知（PR A） | 毎日の通知（`docs/plan-device-records.md` §4）。判定は純関数 `push/decide.py`、本文は `push/payload.py`（`patient_strings.json` の固定文だけ）、送信は `app.state.push_sender`（既定は `push/sender.py` の `WebPushSender`、鍵が無ければ None）、周期は `api/app.py` の `_push_loop`。**`reports`・`timelines`・`regimen_drafts` を読まない** |
| `tests/test_api_*.py` `tests/test_architecture.py` | 各担当 | `fastapi.testclient.TestClient`。runner は `pipeline_fakes.FakeRunner`、editor は偽物。アーキテクチャテストは `ast` で `api/patient.py` の import を検査 |

### W3 後の決定（2026-11-04）
- `GET /api/doctor/visits` に出すのは受付番号のある generating・ready・failed だけ（印刷済み・期限切れは出さない）
- `GET /api/doctor/skills` は `{skills: [{name, version}], invalid: [{name, code, required}]}`（壊れた Skill があっても医師画面を止めない。設定画面は `invalid` を表示する）
- Skill の承認・却下はどちらも Skill ごとのファイルロック（flock）の中で行い、握られていれば 409 `{"error":"busy"}`。`reject_change(conn, id, *, skills_home=None)`（API は skills_home を渡す）
- `SdkSkillEditor(settings=None, query_fn=None)`。医師 API のルーターは login/logout 以外に `Depends(require_doctor)` を付ける
- 想定外の例外は 500 `{"error":"internal_error"}` と `X-Error-Id` ヘッダ。ログには型名と相関IDだけ
- `/docs`・`/redoc`・`/openapi.json` は無効

### W4 後の決定（2026-11-04）
- db に `save_visit_result(conn, vid, *, timeline, html, data, status, fallback)`（timeline・report・status を1つのトランザクションで。印刷済み・期限切れは `VisitClosedError` で何も変えない）と `seed_patient(conn, *, patient_id, regimen, courses, entries: Sequence[Entry]) -> bool` を足した。`PATIENT_ID_PATTERN`・`write_transaction` も公開。**`write_transaction` を入れ子にすると内側で commit される**ので、複数の書き込みは db の専用関数で1つにまとめる
- 「期限切れ」は `reception_no IS NULL` だけでなく `expires_at > now` も見る（purge 前でも保存・状態変更・Claude 呼び出しをしない）。§7d の手順5は `save_visit_result` を1回
- フロントの契約は `scripts/dump_api_fixtures.py` が実 API から書き出す `frontend/src/test/fixtures/api/*.json` で検査する（`backend/tests/test_dump_api_fixtures.py` が古くなっていないことを確かめる）。API を変えたら fixture を書き直す

### 2026-11-04 明け方の決定
- 起動時（lifespan。purge の後に1回だけ）に、受付番号が残っていて期限内の status=generating の受診を `api/orphans.recover_orphans` で回収する: Claude を呼ばずにフォールバック（AI変換なし）のレポートを作って ready にする（変換は同じプロセスの BackgroundTasks で動くので、止まった・再起動したプロセスの生成中は二度と終わらない）。ログ `orphan_recovered`。単一プロセス（`--workers 1`）が前提。稼働中も10分ごとの掃除で、最後のログ（無ければ受付）から `pipeline_timeout_s + 120` 秒以上動きの無い生成中を同じ方法で回収する（`orphans.recover_stale`。convert は `pipeline_timeout_s` で打ち切られるので、動いている生成は奪わない）

- D4 の依頼は、同じ Skill の作業中（diff の無い pending）があれば 409 `busy`。`created_at` から `pipeline_timeout_s` を過ぎた作業中の行は `failed`（`stale_request`）にしてから判定する（`GET /skill-changes` の前にも、30秒の余裕をつけて同じ片付けをする）。フロントは作業中の行を「生成中」と出して3秒ごとに履歴を取り直す
- フロントの通信のタイムアウト: 患者 API 20秒、医師 API 30秒、D4 の依頼 10分（打ち切りは通信の失敗と同じ扱い）
- 医師画面の「印刷」は、同じオリジンの非表示 iframe にレポートを読み込んで親から `print()` を呼ぶ（レポートの CSP は script を止めるため）。失敗したら「レポートを開く」から ⌘P

- 医師 API の状態を変える POST（login 以外。logout を含む）は `require_same_origin`: `Sec-Fetch-Site` が cross-site/same-site、または `Origin` が「要求の Host の origin」とも `public_base_url` の origin とも違えば 403 `cross_origin`（どちらのヘッダも無ければ通す）。リバースプロキシが Host を書き換える構成では `public_base_url` を正しく設定する。frontend を別のサブドメインに置く構成は使えない
- 送り直しの重複防止: 記録の押し直しは端末の同じ ID で置き換わる。受付の送り直しは `client_entry_id` で二重にならない。同じ患者・同じ日・同じ受付番号で期限内の受診があれば作らず、生成も起動しない（`db.create_visit_once`。生成に失敗した受診でも作り直さない）

- `POST /api/doctor/visits/{id}/regenerate`（本文なし、`{ok}`）: 受付番号が残っていて期限内の、failed または ready かつ fallback=True の受診だけを generating に戻して生成をやり直す（`db.begin_regeneration` の条件付き UPDATE。それ以外は 409 `not_regenerable`、無ければ 404）。ログ `regenerate_requested`。D3 の該当行に「AI でもう一度変換」。生成中（やり直しの最中を含む）はレポートを返さず（404）、印刷済みにもしない（409 `generating`）

### UI の見直しで足した経路（2026-11-04 午後、修正ボード）
| 経路 | 応答 |
|---|---|
| `GET /api/doctor/patients`（追加項目） | 各患者に `last_record_date`・`current_course_no`（`config.today()` の今コース）・`next_visit`（今コースの次回受診予定日。今日より前なら null）。無ければ null（D3-2） |
| `GET /api/doctor/patients/{pid}/visits` | その患者の受診を新しい順（印刷済み・期限切れも）。受付番号は消えていれば null、`report_available` は開ける ready か（D4-1） |
| `GET /api/doctor/patients/{pid}/entries` | 直近30件と総数。クローズ回答はコードのまま、自由記載は有無（`has_free_text`）だけで原文は返さない（D4-1） |
| `GET /api/doctor/visits/{id}/unprocessed`（追加項目） | 各記録に `marks: [{start, end}]`（原文の中の疑われた語の位置、code point）。原文の中で見つからない区間には付けない（D7-2） |
| `GET /api/doctor/skills/{name}` | `{name, version, description, questions, text}`（読み取り専用）。書式違いは 400 `invalid_name`、`GET /skills` と同じ一覧に無ければ 404 `unknown_skill`、`skills_dir` の外へのシンボリックリンクは 400、壊れた SKILL.md はその code（D5-2） |

### 医師画面の UX の見直しで足した項目（2026-11-04 夜。経路は増やしていない）
Day は `course.course_for_date` のコースの実投与日を Day1 として数える（次のコースが未登録なら cycle_days を過ぎても数え続ける。`day_of` と同じ）。今日は `config.today()`。コースに矛盾がある患者は、その値だけ null にして応答は止めない（`doctor_records`）。

| 経路 | 足した項目 |
|---|---|
| `GET /api/doctor/patients` | 各患者に `current_day`（今日の今のコースでの Day。今コースが無い・矛盾は null）・`days_since_last_record`（今日 − 最後の記録日の日数。記録が無ければ null）・`record_stale`（最後の記録が今日から3日以上前（今日を含めず3日前以前）、または記録が1件も無い） |
| `GET /api/doctor/patients/{pid}/entries` | 各記録に `course_no`・`day`（記録日のコースと Day。最初の投与の前・矛盾は null） |
| `GET /api/doctor/visits/{id}/unprocessed` | `visit: {id, reception_no, patient_id, visit_date, created_at, status, fallback, report_available}`（見出しと、確かめた後の印刷に使う。`report_available` は受付番号が残っていて期限内の ready）と、各記録に `course_no`・`day` |
| `GET /api/doctor/pipeline/{id}/events` | 同じ `visit`（印刷済み・期限切れは `reception_no` が null） |

### 未処理の記載を伏せ字にして変換し直す（2026-11-04 夜、先生の指示）
医師は文を書かない。原文（生の自由記載）の中の伏せる区間だけを送る。位置は Python の str の位置（code point）の [start, end)（`marks` と同じ。画面は Selection の UTF-16 の位置を code point に直す）。サーバーが区間を検査（範囲内・空でない・昇順・重ならない。`masking.manual.validate_spans`）し、自分で伏せた文を作る。

| 経路 | 入力 | 応答 |
|---|---|---|
| `GET /api/doctor/visits/{id}/unprocessed`（追加項目） | — | 各記録に `doctor_mask: {spans: [{start, end}], confirmed_clear} \| null`（保存済みの医師の伏せ字。許す区間は返さない） |
| `POST /api/doctor/visits/{id}/masks/check` | `{entry_id, spans: [{start, end}]}` | `{entry_id, masked_text, suspects: [{start, end, rule}], reason, sendable, confirmable}`。保存しない。masked_text は送られる文（区間を `[伏せ字]` にしてから正規化・一次）、suspects はその文の位置（start の順。規則が違えば重なりうる）。confirmable は疑いが残り、全ての位置が分かり、仮名ID・受付番号（known_identifier）でない。区間の誤り 422 `invalid_spans`、今の未処理（timeline の unprocessed）にも保存済みの伏せ字にも無い記録は 404 `unknown_entry`、印刷済み・期限切れは 404 |
| `POST /api/doctor/visits/{id}/masks` | `{entries: [{entry_id, send, spans, confirmed_clear}]}`（1〜200件、同じ記録は1回） | `{ok: true, sendable}`（保存した記録のうち変換で送られる件数）。send=true は保存（置き換え）、false は削除。confirmed_clear で確かめて送れない記録は 422 `not_confirmable`。印刷済み・期限切れは 409 `visit_closed`、生成中は 409 `generating`。ログ `doctor_mask_saved`・`doctor_mask_confirmed`・`doctor_mask_removed`（decision `entry:<entries.id>`） |
| `POST /api/doctor/visits/{id}/regenerate`（条件の追加） | — | 開いている ready で医師の伏せ字が1件以上あれば、AI の結果でもやり直せる（`db.begin_regeneration` の1つの条件付き UPDATE。二重に押しても1回だけ） |

- 順序: 生の原文に医師の区間を当てて `[伏せ字]` → 仮名ID・受付番号の照合（当てた後の文で）→ `check_text`（正規化 → 一次 → 二次）→ 依頼文の形（JSON）での二次。`pipeline.inputs.mask_entry_text` が正本で、`prepare_input(doctor_masks=...)` と `report.gate.check_inputs(doctor_masks=...)`（`build_report_data` 経由）の両方が使う（`service._gather` が `db.list_doctor_masks` を読み、両方に同じものを渡す）。H2 は伏せた後の文（masked_texts）と照合する
- 確かめて送る（confirmed_clear）: 保存の時にサーバーが「伏せた後にまだ疑われている区間」を `allowed`（伏せた後の文の位置）として記録する（`pipeline.manual_review.confirmed_mask`）。変換では、その記録のその区間に完全に含まれる検出だけを許し、許した部分文字列を `PreparedInput.allowed_suspects` に入れる。H1（`make_h1(..., allowed=...)`）と convert のコードの段（`masking.manual.detect_in_prompt`）は依頼文全体でその語（JSON の形に直したもの）の出現に完全に含まれる検出だけを無視する（ログ `hook_h1_confirmed`、decision `confirmed:<数>`）。**許す一覧が空なら H1 は今と同じ**。gate は allowed_suspects も記録から作り直して照合する
- `[伏せ字]さん`・`[伏せ字]先生` などの伏せた後の文は二次に掛からない（`tests/test_masking_manual.py`。検出側は変えていない）
- 変換の入力のログ: 医師の伏せ字を使って送った記録があれば `doctor_masks_applied`（`sent:N`）、確かめて許した記録があれば `doctor_confirmed_sent`（`sent:M`）。無ければ何も足さない
- 保持: `doctor_masks` は印刷済み・期限切れでレポートと同じトランザクションで消す（`_erase_results`。purge は doctor_masks だけが残った受診も消す）。生の記録（entries・free_texts）は変えない（spec 13.3）
- 画面（D6）: 記録ごとに「送らない（未処理のまま）」（初め）／「送る（伏せて）」。送る記録は疑われた区間（marks）を初めから伏せ、黒い「伏せ字」の印（button）を押すと戻す。ほかの所は選んで「伏せ字にする」（伏せた区間と重なる・隣り合う選択は1つにまとめる）。「伏せ字を確かめる」で送られる文とまだ疑われる語を出し、確かめて送れるならチェックを出す。下の「伏せ字を保存して AI で変換し直す」で保存 → regenerate → 変換ログへ（送れる記録が0件なら変換しない）。「確かめたらこの画面から印刷」の欄は残す

### 9b. Skill の書き換え（W3-skillchange、`tsutae.skillchange`）
- `SkillEditor` プロトコル: `async edit(work_root: Path, skill_name: str, request_text: str) -> RunStats`。`SdkSkillEditor` は `claude_agent_sdk.query`（`cwd=work_root`、`setting_sources=[]`（分離モード。書き換えに Skill の読み込みは要らず、ファイルの設定も混ぜない）、`allowed_tools=["Read","Edit","Write"]`、`disallowed_tools` に Bash・Web 系・Task/Agent、`permission_mode="acceptEdits"`、hooks は H1（依頼文の二次検出）・H3（`make_work_copy_h3(work_root, skill_name, logger)`。書き込みを作業コピーの SKILL.md ちょうど1つに限る。`workcopy.py`）・H4・PostToolUse の skill_check（`Write|Edit|MultiEdit` の後に写しを `validate_skill_text`・version 不変で検査し、壊れていれば理由を返して同じ会話の中で直させる。2026-11-04 追加）、`max_turns` は 16、`model=settings.model`）。依頼文の H1 に掛かれば編集せず `failed`（`h1_blocked`）
- `request_change(conn, skill_name, request_text, *, editor, settings, skills_home) -> int`: 名前を `SKILL_NAME_PATTERN` で検査 → `skill_changes` を作る → `skills_home/.claude/skills/<name>/SKILL.md` だけを一時ディレクトリ（`tempfile.mkdtemp`）の `skills/<name>/SKILL.md`（`work_copy_path`。`.claude/` の下には置かない。CLI がそこへの書き込みを acceptEdits でも保護し、サーバーには許可を出す人がいないため。2026-11-04）に写す → editor → 写しを読み `validate_skill_text` → **version は元のまま**であること（エージェントに上げさせない。変わっていれば元に戻してから比べる）→ `diff.unified(old, new)`（空なら `failed`・`no_change`）→ `pending`（diff・new_text を保存）。どこで失敗しても `failed` と短い error_code。一時ディレクトリは必ず消す。本体には触らない
- `approve_change(conn, change_id, *, skills_home) -> int`: pending のみ。`base_version` が今の版と違えば `failed`・`stale`。new_text の frontmatter の version を base+1 にして再検証 → 本体へ原子的に書く（同じディレクトリの一時ファイル → `os.replace`）→ `save_skill_version` → approved。**git commit はしない**（版の履歴は `skill_versions` に残す）
- `reject_change(conn, change_id) -> None`: pending のみ rejected
- ログは `PipelineLogger(conn, "skill_change", change_id)`（文面なし）

### 9c. D4 レジメン — フォームとチャット（v1.1、`tsutae.regimen`。spec 9.1、`docs/plan-d4-regimen.md`）
- **形**: `RegimenForm`（pydantic、frozen）
  - `basic`: display_name・code・target・cycle_days
  - `drugs[]`: row_id・name・route `infusion|oral|pump`・`days: list[DayRange]`（`DayRange(start, end)`、複数可）・times_per_day・start_note
  - `side_effects[]`: row_id・phrases・ctcae_terms[]・question_key|None
  - `questions[]`: row_id・key・label・text・answer_type
  - `notes`（補足の指示）
  - `prose: RegimenProse | None`（描画用の文。画面に出さず、`set_fields`・PATCH では書けない。FOLFOX/CAPOX の JSON が埋め、新規は None で既定の文、版 N+1 は版 N から引き継ぐ。中身は既存2本の差分から決める: 冒頭の注記・1コースの補足（「（3週）」）・点滴の日の括弧・持続ポンプの文・内服の補足・improving の例・食い違いの例・まとめた質問の行）
  - `FieldSources`: 欄の id（`basic.cycle_days`・`drugs.<row_id>.start_note` など）→ `doctor_text|standard|doctor_edit`
- **描画（T91）**: `render_regimen_skill(form, version) -> str`（純関数。DB・部品集を見ない。Jinja2 は `StrictUndefined`・`autoescape=False`・`keep_trailing_newline=True`）。FOLFOX/CAPOX は `regimen_forms/folfox.json`・`capox.json` から描いて**今の SKILL.md とバイト一致**（テスト）。frontmatter は v1.0 の鍵＋任意の `display_name`（code と違うときだけ）・`term_keys`（全体の対応と違うものだけ）。質問の label は frontmatter に書かない。描いた結果は必ず `validate_skill_text`（strict）を通す
  - **日付の言い方の表**: 点滴の日の集合 I（route=infusion の全 Day。pump は入れない）・ポンプ抜去日 P（pump の最後の Day）・内服の範囲 O。|I|=1 なら今の行（「点滴の日・投与日・病院で点滴した日（・飲み薬を始めた日）| Day1」）。|I|≥2 なら「記録日以前で最も近い点滴の日（Day1・8・15）。confidence を下げる（0.6 未満）」と候補を列挙し、「点滴の次の日」はその次の日（§2「〜から」の例も「→ 上の点滴の日の次の日。Day1 なら Day2」。|I|=1 は今の「→ Day2」）。P があれば「ポンプを外した日 | DayP」「ポンプを外した次の日 | DayP+1」、無ければ CAPOX と同じ「『ポンプ』が出てくる表現」の行。O は「飲み薬を始めた日 | 最初の範囲の始まり」、「飲み薬が終わった日・最後に飲んだ日」は各範囲の終わりの日を候補に並べた1行、範囲の間と最後の範囲の後の始まりを候補に並べた「飲み薬が休みの日・休薬に入った日」の1行、範囲が2つ以上なら2つ目以降の始まりを候補に並べた「飲み薬を再開した日・また飲み始めた日」の1行（候補が2つ以上なら「記録日以前で最も近い…」と confidence を下げる。範囲が1つなら今の CAPOX の文言。範囲が cycle_days まで続くならその後の休薬の始まりは出さず、休薬が1つも無ければ休薬の行は出さない）。Day の範囲は早い順に並べ、重ねず、隣り合わせない（つなげて1つにする）。直し方の Day が同じ言い方は1行にまとめる。曜日の3行は共通
  - **まとめた質問の行**（§5）: questions にある key だけを並べる。既知の3つ（nausea_appetite・numbness・stomatitis）は今の文。それ以外は3択の質問で、その key につながる side_effects の行の用語が合わせて2語以上あるものだけを、その行の phrases から（1つの症状だけの質問は「まとめた」質問ではない）。1つも無ければ描かない
  - **補足の指示**: 空でなければ最後の節の後に「## 10. 補足の指示（施設の決まり）」と本文。空なら描かない。ファイルは改行1つで終える
- **値の検査**（`set_fields`・PATCH の両方）: 投与スケジュールの規則（spec 9.1）、`detect_identifiers`（識別名・質問の key を含む全ての文の欄）、薬の量の語、frontmatter に入る値は YAML で読み戻して同じか（識別名の `NO`・key の `no`/`null` のような YAML 1.1 の真偽・null も拒否）、表のセルに改行・`|` が無いか、制御文字・見えない文字（Cc・Cf・Zl・Zp。補足の指示は LF とタブだけ通し、CR は拒否）が無いか。掛かれば欄の id と理由を返す（`validate_form(form) -> list[FieldIssue]`）
- **逆向き**: 既存の版を開くとき `form_from_skill(name, version)`。FOLFOX/CAPOX@1 は上の JSON、D4 で採用した版は `regimen_forms`（SKILL.md を読み戻して解析はしない）
- **用語と質問の対応**: `term_keys_for(skill_version)` = `ctcae_terms.json` の全体の対応 ＋ その版の `term_keys`。`checks.py`（OutputContext）・`report/validate.py` は、記録ごとに（Entry.skill_version）その版の対応を使う（`PreparedInput.entry_versions`・`other_versions`）。term-mapper の用語の一覧は入力の版の対応のまま（Claude に送る JSON と評価済みの依頼文を変えない）で、版の混ざる受診で違う key を付けた出来事は checks が差し戻す。FOLFOX/CAPOX@1 は `term_keys` が無いので今と同じ
- **下書き（T93）**: `regimen_drafts`。状態 `open → working（1往復の間）→ open`、`adopted`・`discarded` で閉じる。既存の版から作った下書きは同じ regimen に open/working が1つ。新規は code が決まるまで regimen NULL。`working` の間の PATCH・preview・adopt・discard は 409。往復ごとに `generation` を上げ、結果は世代が同じときだけ反映する。`working` のまま上限を過ぎた行は open に戻し、会話に失敗の行を残す
- **1往復（T94）**: `RegimenChat` プロトコル `async turn(draft: TurnInput, text) -> TurnResult`（`tsutae.regimen.chat_types`）。`SdkRegimenChat`（`chat_sdk`）は `query()`（cwd は空の一時ディレクトリ・`setting_sources=[]`・`--no-session-persistence`・`env=NO_CLAUDE_MD_ENV`・`max_turns`=`regimen_max_turns`（既定 12）・`max_budget_usd`=`regimen_max_budget_usd`（既定 1.0）・`permission_mode="dontAsk"`・`allowed_tools` は `mcp__tsutae_regimen__{set_fields,ask,propose_questions}` だけ・`disallowed_tools` は 9b の一覧＋Read/Edit/Write＋ToolSearch＋使わない組み込みツール（pipeline と同じ）・hooks は H1 と H4（サブエージェント無し））。HTTP は応答まで待つ（上限 `regimen_turn_timeout_s`、既定 90 秒。読み出しの回復は上限＋15 秒の `regimen_recover_after_s`）。本体は `chat_turn.run_turn`: 入力の文と依頼文の全体に `detect_identifiers`（掛かれば Claude を呼ばず 422 h1_blocked。issues に掛かった場所 text / prompt と規則の名前だけ。保存しない）→ `begin_working`（generation を上げる。読んだ時と form_json・sources_json が同じときだけ。違えば 409 conflict）→ `asyncio.wait_for(chat.turn)` → 結果の検査し直し（validate_form・識別名・体温・prose）→ 返答の文と ask に H1（掛かれば固定の文・ask を落とす）→ `finish_turn`（working かつ同じ generation のときだけ。当たらなければ捨てる）。時間切れ・例外は `fail_turn`（先生の文と失敗の行だけを足して open。`chat_fail`）。begin_working の後で外に抜ける例外（取り消し・結果の書き込みの DB の失敗など）も、できる範囲で `fail_turn`（reason は cancelled か internal_error）してから投げ直す（`rescue`。working のまま残さない）。**依頼文とツールでは行を row_id でなく ref（`drugs.1`・`drugs.1.days`）で指す**（`chat_handles`。row_id の `q-fever`・`d-fu-pump` は H1 の id_like に掛かるため。Claude が足す行の row_id はサーバーが `drug1`・`effect1`・`question1` と振る）。依頼文（`chat_prompt`、文字列の定数）: 今のフォーム（ref つきの JSON。prose は入れない）・出どころ（先生が入れた欄・AI が入れた欄）・まだ入っていない必須の欄・欄の決まり・部品集・CTCAE の用語の一覧・直近の会話（8行。欄の id は出さない。聞いた問いの選択肢は「」で囲んでつなぐ（空白・「/」は long_digits の区切り）。描いて H1 に掛かる行は固定の文に置き換える）・規則（先生の文に無い値は source=standard／分からなければ ask で1問ずつ選択肢つき／薬の量は持たない／先生が入れた欄は overwrite_requested が無ければ変えない／体温の質問は外せない／§5 の質問の目安）。ツール（`chat_tools`・`chat_propose`）は DB に書かず `ChatSession` に当てる: 入力は pydantic（`chat_args`）、値は `edit.apply_patch`（出どころ doctor_text で当て、standard の欄を付け替える）。拒否は is_error で「ref: 理由（コード）」を返して直させる。`ask` は欄の ref（か節の名前）・問い・選択肢 2〜4 で1往復に1問（次の依頼文に入る形 `ask_line` にも H1）。`propose_questions` は部品集の key か新しい3択の質問（部品集の key・予約語・重複を拒否。source=standard の提案は基本・薬・注意する症状の必須の欄がそろうまで not_ready）。会話の行（`chat_rows`）: 先生 `{role:doctor,text,generation,at}`、Claude `{role:assistant,text,changed:[欄の id],ask,proposed,reply_hidden,generation,at}`、失敗 `{role:system,kind:turn_failed,reason,generation,at}`。会話の文面は `regimen_drafts.chat_json` だけに置き、`PipelineLogger(conn, "regimen_chat", draft_id)` には `h1_check`・`turn_start`・`regimen_tool`（ツール名と accept / reject:<コード>）・Hook（H1・H4）・`turn_end`（秒・トークン・費用）・`turn_counts`（呼んだ数・拒否の数・ターン数・変えた欄の数。SDK の jsonschema が handler の前に止めた呼び出しは数えない）・`reply_hidden`・`turn_discarded`・`turn_failed`・`internal_error`（例外の型名だけ）だけ。起動時は `recover_abandoned_turns`（working を全て open に）を `recover_interrupted_adoptions` の前に呼ぶ。`REGIMEN_ALLOWED_TOOLS`・disallowed・H4 の許可一覧は値でテストに固定し、`decisions.md` に記録
- **確認と採用（T93）**: `preview(draft)` は AI の値の一覧・SKILL.md（新規は全文、既存は unified diff）・患者の見本・検査結果と `confirm_token`（正規化した form_json＋sources_json＋base_version のハッシュ）を返す。`adopt(conn, draft_id, confirm_token, ai_values_confirmed, *, skills_home, timeout_s)`（`tsutae.regimen.adopt`）は必須・描画・バリデータ・token の照合・stale・「患者のいるレジメンで日数・Day・抜去日を変えていない」をやり直す。新規は `regimen-<code>/` を排他で作り（既にあれば 409 `code_taken`）SKILL.md を原子的に置いて版1、既存は版 N+1（`base_version` が今と違えば `stale`）。`skill_versions` と `regimen_forms` を同じトランザクションで書く。新しい質問を `question_library` に入れる。採用・破棄で `chat_json` の文面を消す。患者のいるレジメンの日程は、書き込みのトランザクションの中（最初の INSERT の後）でもう一度確かめる。書き順は「ファイルが先・DB が後」なので、SKILL.md を置いた後・commit の前にプロセスが落ちた場合は、起動時（`ensure_skill_versions` の後）に `recover_interrupted_adoptions`（`tsutae.regimen.recover`）が、開いた下書きを描いた文と登録された版の文がバイトで一致するときだけ `regimen_forms`・部品集・adopted を補う（一致しなければ警告だけ）。新規で SKILL.md の無いフォルダ（一時ファイルだけ）が残っていれば消す
- **DB の移行（T93 で仕組み、T94・T95 で使う）**: `migrate_db(conn)` を `init_db` の中で schema.sql の前に呼ぶ。`sqlite_master` の CREATE 文を見て、古い CHECK があるときだけ SQLite の「12-step generalized ALTER TABLE」で表を作り直す（トランザクションの外で `PRAGMA foreign_keys=OFF` → `BEGIN IMMEDIATE` → 新しい表 → 全行を写す → DROP → RENAME → 索引を作り直す → `PRAGMA foreign_key_check` が空でなければ ROLLBACK → COMMIT → finally で `foreign_keys=ON`）。対象は `pipeline_logs`（run_kind に regimen_chat。T94 より前に要る）と `patients`（regimen の CHECK を外す。T95）。何度呼んでもよく、行数と中身が変わらないことをテストで確かめる
- **レジメンの一覧（T95）**: `list_regimens(skills_dir)`（`tsutae.skills.catalog`）は skills_dir 直下の `regimen-*/SKILL.md` を検査して読み、識別名・Skill 名・版・表示名（`display_name`、無ければ識別名）を返す（FOLFOX・CAPOX を先に、ほかは識別名の順。壊れた SKILL.md は載せず警告だけ）。全ての `regimen-*` で名前は `regimen-` + 識別名の小文字（違えば `regimen_mismatch`。loader の検査）。`schemas.Regimen` は識別名の書式の `str`（合成データの `SyntheticPatient.regimen` と seed は FOLFOX/CAPOX のまま）。`GET /api/doctor/regimens` が一覧のうち `skill_versions` に版のあるものを返し（新規の採用はファイルが先・DB が後なので、その途中では選べない）、`POST /patients` はそれに無い識別名を 422 `invalid_input`。`patients.regimen` の CHECK は `migrate_db` で外す（rowid も写す）。記録の版の解決（`pipeline.versions` の `questions_by_version`・`regimen_skills_by_version`）は skill_versions にある全ての `regimen-*` を引く。用語の対応を記録ごとに引くため、`PreparedInput` は記録の版（`entry_versions`）と入力の版と違う版の材料（`other_versions`: term_keys と質問の key）を持つ（Claude に送る JSON の外。gate が記録・版の質問集と照合する）。term-mapper の一覧は入力の版の対応のまま（記録に版を持たせると依頼文が変わる）で、版の混ざる受診で古い版の記録を新しい質問につなげた出来事は checks が期待の key つきで差し戻す。紙の短い名前は既知の6問は `SHORT_LABELS`、それ以外は今の版の form の label（`regimen.labels`。form の無い版は質問文）。医師画面（D2）の記録の回答には記録の版の label（`question_label`）を付け、画面は既知の6問の表を先に使う。紙のヘッダは表示名（`ReportHeader.regimen_label`。FOLFOX/CAPOX は None で識別名）
- **旧 D4 の制限（T95）**: `request_change`（と `POST /skill-changes`）は `regimen-*` を行を作らずに 400 `use_regimen_editor`（editor を呼ばない）。T95 より前に作られた pending の `regimen-*` の変更は、`approve_change` が承認せず failed（`use_regimen_editor`）にする（本体・skill_versions は変えない。却下はできる）。テスト・`run_demo_skill_change.py` の既定（偽の editor は引用の最大件数を 30 → 20）・API の fixture は `report-format-default` に移した。既存の版に質問を足す結合テスト（test_e2e_flow の (10)）は D4 レジメンの API（下書き → 直接編集 → 確認 → 採用）で版2を作る

## 9. フロント（W1 骨組み → W4 画面）
- React 18 + Vite 5 + TypeScript + react-router 6。vitest + Testing Library（jsdom）。Prettier（2 スペース、セミコロンあり）
- 開発時は Vite の proxy で `/api` → `http://127.0.0.1:8000`（uvicorn の既定の待ち受け。macOS では localhost が ::1 に解決され届かないため）
- ルート: 患者 `/register` `/today` `/history` `/visit` `/settings`、医師 `/doctor/login` `/doctor`（印刷待ち） `/doctor/patients` `/doctor/patients/:pid` `/doctor/settings` `/doctor/pipeline/:visitId` `/doctor/unprocessed/:visitId`
  - `/doctor/settings`（D4。v1.1・T96）は画面の中のタブで2つに分ける（経路は1つのまま）: 「レジメン」＝左のフォーム＋右のチャット（`components/doctor/regimen/`。タブを開くと `POST /regimen-drafts {skill}` で版 N+1 の下書き、「＋ 新しいレジメン」は `{from: "new"}`。確認 → 採用 → 登録済み）／「レポートの形式（一文で頼む）」＝旧 D4 の一文 → 差分 → 承認（`pages/doctor/ReportFormatSettings.tsx`。選べるのは `report-format-*` だけ、初めは `report-format-default`）。一度開いた種類は描いたまま `hidden` で隠す（往復の最中に種類を替えても下書きの画面を失わない）
- 患者画面の文字列は `usePatientStrings().t(key)` からのみ出す（直書きしない。テストで検査）。質問文は API の `questions[].text`
- 型は `src/api/types.ts`（schemas.py の API に出る部分を写す）、呼び出しは `src/api/patient.ts` `src/api/doctor.ts`
- **W2b の決定**: 患者 API・医師 API の 2xx 応答は実行時に形を検査し、違えば `error.network` 相当の表示にする（真っ白にしない）。患者側・医師側とも ErrorBoundary を置く。患者画面の直書き検査は「患者のファイルの文字列リテラルに日本語を含めない」「JSX のテキストに英字を書かない」の2つ（変数経由の英字は検査の外。既知の限界として README に書く）。Skill 変更の差分が空なら失敗として扱い承認させない。`Course.note` は200字まで（schemas.py で強制）

## 10. 時計・デモ
- `TSUTAE_TODAY=2026-11-09` でデモの「今日」を固定。`scripts/seed_demo.py` が合成データを DB に入れる（W3）
- 撮影と通しは `scripts/seed_demo.py --device-records`（患者・コース・日付の印だけ）の新しい DB で動かし、`TSUTAE_DEMO_TOOLS=1` でデモ患者の設定に出る「見本の記録を入れる」から端末へ記録を入れる（§12・§13。手順は `docs/demo-script.md`）。`make seed` の既定の動きは、テスト・`run_demo_visit.py`・評価のために変えない

## 11. 毎日の通知（PR A。`docs/plan-device-records.md` §3・§4）

決まり（回数・文・送る期間）は仕様書 §4.1。ここには実装の形だけを書く。

| ファイル | 中身 |
|---|---|
| `push/decide.py` | 純関数。`decide_send(at, *, notify_time, last_sent_date, marked_today, last_day1, cycle_days) -> Decision`（`due`・`sent_today`・`before_time`・`window_passed`・`marked`・`no_course`・`period_over`）。`SEND_WINDOW` は 10 分、`GRACE_DAYS` は 14。日付と時刻は JST で見る |
| `push/payload.py` | `notification_payload() -> str`（JSON: title・body・url・badge）。**引数を取らない**。文は `patient_strings.json` の `notify.title`・`notify.body` |
| `push/sender.py` | `PushSender` プロトコル `sender(target, payload)`、本物は `WebPushSender`（pywebpush。TTL 3600 秒・タイムアウト 10 秒）。送信先のエラーは `PushSendError(status_code)`。`load_vapid(settings) -> VapidConfig \| None` |
| `push/dispatch.py` | `send_due_once(settings, sender, at=None) -> PushCounts`（全ての登録を判定して送る。1件の失敗で止めない）、`send_test_once(settings, sender, subscription_id)`（試送。印・期間・時刻を見ず、`last_sent_date` も使わない）。送れなかったときのログは型名と状態コード（`push.send_failed error_type=... status=...`）、試送の結果は `push.test_done result=...`。仮名ID・endpoint は出さない |
| `api/patient_push.py` | 下の4経路。`PushTestLimiter`（プロセス内の dict。登録ごとに1分に1回、患者ごとに1分に登録の上限の回数まで）、`is_push_service_url`、`send_test_later` |
| `api/app.py` | `_install_push`（`app.state.push_sender`・`push_public_key`・`push_test_limiter`・`push_test_delay_s`）、`_push_loop`（`PUSH_INTERVAL_S` = 60 秒ごとに `asyncio.to_thread(send_due_once, ...)`。`_purge_loop` と同じく lifespan の中。`--workers 1` が前提）。`create_app(push_sender=...)` で偽物に差し替える |
| `db/repo_record_marks.py` | `add_record_mark`・`undo_record_mark`（§12）、`upsert_mark_row`（`insert_entry_rows` の中でも呼ぶので、seed と `add_entry` は行と同じトランザクションで印が付く）、`marked_patients`、`last_record_dates`（D1）、`backfill_record_marks`（`init_db` のたび。今ある印は変えない。受付で受け取った行は数えない） |
| `db/repo_push.py` | `upsert_push_subscription`（endpoint で一意。同じ患者なら `last_sent_date` を保ち、別の患者の番号で登録し直したら行をその患者に移し、その患者の消した登録の送信日を引き継ぐ。1人の患者の行は `MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT` = 5 までで、超えたら今の endpoint 以外の古い行を消す。消す行の送信日も残す）、`claim_push_send`・`release_push_send`、削除と読み出し |
| `scripts/gen_vapid.py` | 鍵を標準出力に出すだけ。ファイルに書かない |

| 経路 | 入力 | 出力 |
|---|---|---|
| `GET /api/patient/push-config` | — | `{available, public_key}`（使えないときは `false`・`null`） |
| `PUT /api/patient/{pid}/push-subscription` | `{endpoint, keys: {p256dh, auth}, notify_time}`（notify_time は 30 分刻み。省くと 20:00） | `{ok: true, notify_time}`。鍵が無ければ 503 `push_unavailable`、形が違えば 422、送信先に消された endpoint は 410 `push_subscription_gone` |
| `DELETE /api/patient/{pid}/push-subscription` | `{endpoint}` | `{ok: true}`（無くても 200） |
| `POST /api/patient/{pid}/push-test` | `{endpoint}` | `{ok: true}`。応答の後に 10 秒待って1通送る。その患者の登録に無ければ 404 `not_found`、1分以内の2回目と、患者ごとの1分の上限を超えたときは 429 `push_test_too_soon`、鍵が無ければ 503 `push_unavailable` |

- **送る順**: 判定 → `claim_push_send`（先に今日の分を取る）→ 送る → 送れなければ `release_push_send` で戻す（窓の 10 分の間は次の周期でやり直す）→ 404・410 は今日の分を戻してから登録を消し、endpoint を `push_gone_endpoints` に覚える。応答の前にタイムアウトしたときだけ二重に届く余地がある
- **鍵**: `TSUTAE_VAPID_PUBLIC_KEY`・`TSUTAE_VAPID_PRIVATE_KEY`・`TSUTAE_VAPID_SUBJECT`（`mailto:` か `https://`）。全て無ければ警告なしで使えない。欠け（`missing`）・subject の誤り（`bad_subject`）・読めない鍵（例外の型名）・組でない（`key_mismatch`）は警告に理由のコードだけを出して使えない。どれも起動は止めない
- **入力の検査**: endpoint は既知の送信サービスの https だけ（`fcm.googleapis.com`・`*.push.apple.com`・`*.push.services.mozilla.com`・`*.notify.windows.com`。ポートは 443、ユーザー情報は不可）。`\` を受けず、ホストは英数字・`.`・`-` だけで、送信に使う urllib3 の読み方でも同じホストになること。本物の送信はリダイレクトを追わない。p256dh は 65 バイトの P-256 の点、auth は 16 バイト
- **ログ**: 件数と例外の型名、送信先が返した状態コードだけ。仮名ID・endpoint・例外の文面を出さない。件数（`push.done`）と試送の結果（`push.test_done`）も WARNING で出す（uvicorn の既定で INFO は残らない）
- **守ること**: 通知のモジュールは `reports`・`timelines`・`regimen_drafts` を読まない。本文は全ての患者で同じ（`tests/test_architecture.py`）

**フロント**

| ファイル | 中身 |
|---|---|
| `frontend/public/sw.js` | 通知専用。`push` は `waitUntil` の中で必ず `showNotification`（本文が読めなければタイトルだけ。**送るかどうかはサーバーが決め、端末で握りつぶさない**）。`notificationclick` は `/today` を開く（開いている患者の画面を使い、`/doctor` と別のタブで開いたレポート `/api/doctor/...` は動かさない。すでに `/today` なら移動せず、`tsutae.open-today` の知らせを送って手前に出す）。**`fetch` のハンドラを書かない**（`homeScreen.test.ts`） |
| `api/patientPush.ts` | 4経路の呼び出し。応答は形を検査する。endpoint は本文で送る |
| `patient/pushDevice.ts` | 端末の API の包み。Service Worker の登録は `subscribeDevice`（設定でオンにしたとき）だけ |
| `components/patient/pushStatus.ts` | 純関数 `pushStatusOf`（`unsupported`・`no_key`・`denied`・`on`・`off`）と選べる時刻 |
| `components/patient/pushState.ts`・`pushActions.ts`・`usePushSettings.ts` | 状態を読む／端末とサーバーの登録を揃える／画面の状態。許可を求めるのはボタンの onClick の最初だけ |
| `components/patient/pushResend.ts` | オンの端末の登録を送り直す。アプリを開いたとき・戻ってきたとき（`PatientLayout`）と番号を登録したとき（P0・番号の入力欄）。送る時刻は順番が来たときの端末の時刻。410 なら端末でも解除し、設定の画面へ知らせる（`onSubscriptionDropped`。画面がまだ無ければ次に開いたときに1回だけ）。設定と案内の帯は、送り直しと時刻の保存が終わってから状態を読む |
| `components/patient/NotifySettings.tsx`・`pages/patient/Settings.tsx` | P5（`/settings`）。文言は全て `patient_strings.json` |
| `components/patient/NotifyBanner.tsx` | オフでオンにできるときだけ、今日の記録の欄の下に出す案内の帯 |
| `patient/notifyTime.ts` | 設定に出す時刻の写し（localStorage の `tsutae.notify_time`）。正本はサーバー。写しは PUT が受け入れられた時刻で書く（`pushActions.saveSubscription` が PUT を1本ずつ順に送る） |
| `components/patient/useNewDayCheck.ts` | 開いたまま日付が変わった今日の記録に気づく。戻ったとき（`visibilitychange`）と通知を押したとき（`sw.js` の知らせ）に `GET /questions` を読み、画面の今日とサーバーの今日が違うときだけ `pages/patient/Today.tsx` が読み直す。同じ日は完了の画面も書きかけも残す |
| `patient/useClearNotifications.ts` | アプリを開いたとき・戻ってきたときに、バッジと表示中の通知を消す（`PatientLayout`） |

**動かす環境**: 通知には HTTPS が要る。手順は `README.md` の「動かし方」（Tailscale Funnel → `vite preview` の 5173 → `/api` は 8000 へ。開発サーバーは出さない）。実機の確認は未実施（仕様書 §9）。

## 12. スマホ保存の backend（PR B。`docs/plan-device-records.md` §5）

決まりは仕様書 §5。ここには実装の形だけを書く。記録の中身はスマホに置き、受付のときだけサーバーへ届く。変換は今までどおり `entries` を読む。

| ファイル | 中身 |
|---|---|
| `api/patient_device.py` | 下の表の印・範囲・受診日・登録の解除。本文に記録の中身の欄を持たない |
| `api/patient_demo.py` | 撮影の見本（`TSUTAE_DEMO_TOOLS=1`。`Settings.demo_tools`） |
| `api/visit_entries.py` | 受付の記録の本文（`VisitEntryIn`）と検査（`received_entries`）、送る範囲（`visit_window_of`） |
| `api/skill_questions.py` | `version_questions`（その版の質問集） |
| `api/body_limit.py` | `BodyLimit`。`POST /api/visit` の本文を読みながら数え、5MB を超えたら 413 `body_too_large` |
| `db/repo_received.py` | `ReceivedEntry`、`insert_received_rows`（ある ID は飛ばす）、`erase_received_rows`（開いた受診が他に無ければ消す）。呼び出し側のトランザクションの中で動く |
| `db/repo_visits.py` | `create_visit_once(..., entries)` で受診と記録を同じトランザクションに。`mark_printed`・`purge_expired` が同じトランザクションで受け取った記録を消す |
| `scripts/seed_demo.py --device-records` | 患者・コース・日付の印だけを入れる。既定の動きは変えない |

| 経路 | 入力 | 出力 |
|---|---|---|
| `POST /api/patient/{pid}/record-marks` | なし | `{record_date, recorded_at}`（サーバーの時計。ミリ秒に揃える） |
| `POST /api/patient/{pid}/record-marks/undo` | `{recorded_at, clear_mark}`（`recorded_at` は印の応答の値） | `{ok: true}`。`recorded_at` から 10 分を過ぎた・先の時刻・その後に受付がある・その記録を受付で受け取っている（同じ受付番号の送り直しを含む）→ 409 `not_undoable`。`clear_mark` なら `recorded_at` の日の印を消す（後から付いた印は残す）。何度呼んでもよい |
| `GET /api/patient/{pid}/visit-window` | — | `{start, end}`（前コースの Day1〜今日。前コースが無ければ今コースの Day1）。今コースが無ければ 409 `no_course` |
| `GET /api/patient/{pid}/visit-days` | — | `{visits: [{visit_date, received_at}]}`（新しい順。受付番号・状態は返さない） |
| `POST /api/patient/{pid}/unregister` | `{endpoint}`（string か null） | `{ok: true}` + Cookie を消す。その登録を消す。`record_marks` は消さない |
| `GET /api/patient/{pid}/demo-config` | — | `{demo_tools}`（環境変数があり、デモ患者のときだけ true） |
| `GET /api/patient/{pid}/demo-entries` | — | `{entries: 端末の形}`（今日までの合成データ。ID は `demo-<seq>`）。それ以外は 404 |

**端末の形**（`demo-entries`・IndexedDB）: `{pid, client_entry_id, recorded_at, record_date, kind, by_proxy, skill_version, answers: [{question_key, value, temperature, question_text}], free_text}`

**受付で送る形**（`POST /api/visit` の `entries[]`）: 端末の形から `pid` と `question_text` を外したもの。知らない項目は 422。

- 検査: 500 件まで。ID は小文字の UUID か `demo-<数字>`（同じ本文に同じ ID があれば 422）。`recorded_at` は時差つきで、JST の日付が `record_date` と同じ。`kind` は中身と合う。記録日は範囲内。`skill_version` はこの患者のレジメンの登録済みの版で、回答はその版の質問集に照らす。1件でも不正なら全体を 422 にして受診も作らない。今コースが無ければ 409 `no_course`
- 同じ患者の同じ ID は入れない。送り直しで新しい ID の記録が増えても変換はし直さない（PR C の範囲）
- 受け取った記録は日付の印を書かない。起動時の `backfill_record_marks` も数えない
- 印刷済み・期限切れで、その患者に開いた受診（受付番号が残り期限内）が他に無ければ、`client_entry_id` のある行を消す。`client_entry_id` の無い行と日付の印は消さない
- D1 の最後の記録日は `record_marks` から出す。D2 の記録の一覧はそのまま（受付の間だけ行がある）
- `fixed_rules.notices_for` は Python の側の判定で、画面のコードと同じ表（`frontend/src/test/fixtures/fixed_rule_cases.json`）で確かめる

## 13. スマホ保存の frontend（PR B。`docs/plan-device-records.md` §5.1〜§5.5・§5.8〜§5.10）

| ファイル | 中身 |
|---|---|
| `patient/deviceStore.ts` | IndexedDB の薄い包み（DB `tsutae`、store `entries`、キー `client_entry_id`、索引 `pid_record_date` = `[pid, record_date]`）。読むときは必ず仮名ID で絞る。失敗は例外で返す。接続は操作ごとに開いて閉じ、トランザクションの完了で解決する。起動ごとの最初の保存の後に `navigator.storage.persist()` を1回試す |
| `patient/recordEntry.ts` | 記録の順序。`recordEntry`（`POST record-marks` → 応答の時刻で端末に保存）、`undoRecord`（同じ日の記録を読む → `record-marks/undo` → 端末から消す）、`toDeviceEntry`（質問の文の写しを持たせる）、`newClientEntryId` |
| `patient/fixedRules.ts` | `noticesFor(entry, fixed_rules)`。`api/fixed_rules.py` と同じ判定で、同じ表（`src/test/fixtures/fixed_rule_cases.json`）でテストする |
| `api/patientDevice.ts` | §12 の経路の呼び出しと応答の検査。`POST /api/visit` の `entries` は `api/patient.ts` の `submitVisit` |
| `components/patient/TodayForm.tsx` | `client_entry_id` を入力の開始時に作り、押し直しても同じ（「追加で記録する」・取り消しの後で作り直す）。印か保存が失敗したら入力を残して `error.generic`。保存できたら `onSaved`（バッジと表示中の通知を消す） |
| `components/patient/HistoryList.tsx` | P2。端末の記録と `GET visit-days` を読み、`historyRows` で並べる |
| `patient/visitEntries.ts` | P3（§5.5）。`sendVisit`（`GET visit-window` → 端末の記録を読む → 範囲内だけ `POST /api/visit`）、`toVisitEntry`（`pid` と質問の文の写しを外す）。記録を読めなければ例外で返し、空のまま送らない |
| `patient/standalone.ts` | §5.8 の判定の純関数。`needsHomeScreenGuide`（iPhone・iPad で、`navigator.standalone` でも `display-mode: standalone` でもない）、`suggestsHomeScreen`（Android のブラウザ）、`readDisplayEnv` |
| `layouts/PatientLayout.tsx`・`components/patient/AddToHomeGuide.tsx` | 判定が真なら、どの患者の経路でも案内だけを出す。ページも通知の処理も動かさず、API は定型文の GET だけ。URL の `pid` は形が正しいときだけ大きく見せ、保存も登録もしない。医師の経路はこの外枠を通らない |
| `components/patient/PatientNav.tsx` | 下の4つのタブ。幅は文字の長さで分ける（`patient.css`。幅 360px 以上で全て1行） |
| `components/patient/DeviceReset.tsx`・`resetDevice.ts` | §5.9。画面の中の2段階の確認の後、送り直しの PUT を待ち、`POST unregister` → 通知の登録の解除 → 端末の記録 → 仮名ID の順に消す。1つが失敗しても次へ進み、残れば知らせて押し直せる |
| `components/patient/DemoEntries.tsx` | §5.10。`GET demo-config` が真のときだけ出す。`GET demo-entries` を端末に保存する（同じ ID なので増えない） |

テストは dev 依存の `fake-indexeddb` を `src/test/setup.ts` で入れ、テストごとに空の DB から始める。

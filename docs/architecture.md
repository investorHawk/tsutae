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
| patients | id TEXT PK（仮名ID。`P-` + 英大文字数字8桁、`secrets` で生成）, regimen TEXT CHECK(FOLFOX/CAPOX), created_at |
| courses | id INTEGER PK, patient_id FK, course_no INT, infusion_date, planned_date NULL, next_visit NULL, note NULL, UNIQUE(patient_id, course_no) |
| entries | id INTEGER PK, patient_id FK, recorded_at, record_date（recorded_at の JST 日付）, kind CHECK(too_sick/answers/free_text/mixed), by_proxy INT, skill_version TEXT（例 `regimen-folfox@1`） |
| closed_answers | entry_id FK ON DELETE CASCADE, question_key, value CHECK(none/present/hard/not_measured/measured), temperature REAL NULL, PK(entry_id, question_key), CHECK((value='measured') = (temperature IS NOT NULL)) |
| free_texts | entry_id PK FK ON DELETE CASCADE, text TEXT NOT NULL（原文。Claude には送らない。送るのは伏せ字後） |
| visits | id INTEGER PK, patient_id FK, reception_no TEXT NULL（印刷済み・期限切れで NULL にする）, visit_date, created_at, status CHECK(generating/ready/printed/failed), expires_at, fallback INT DEFAULT 0, course_no INT NULL |
| timelines | visit_id PK FK ON DELETE CASCADE, json TEXT（`Timeline`） |
| reports | visit_id PK FK ON DELETE CASCADE, html TEXT, data_json TEXT（`ReportData`） |
| pipeline_logs | id PK, run_kind CHECK(visit/skill_change), run_id INT, ts, event TEXT, hook_name NULL, agent_type NULL, tool_name NULL, decision NULL, duration_ms NULL, tokens_in NULL, tokens_out NULL, cost_usd NULL — **文面は入れない** |
| skill_changes | id PK, skill_name, requested_text, diff TEXT NULL, new_text TEXT NULL, base_version INT, new_version INT NULL, status CHECK(pending/approved/rejected/failed), error_code TEXT NULL, created_at, decided_at NULL |
| skill_versions | skill_name, version INT, content TEXT（SKILL.md 全文）, questions_json TEXT NULL（regimen のみ）, approved_at, PK(skill_name, version) |

`skill_versions` は「その日の記録に使った質問集」を後から引くためのスナップショット（未設問「−−」の表示に使う）。起動時に現在の SKILL.md が未登録なら登録する。

### W1-db の公開関数（`tsutae.db`）
- `connect(path: Path) -> sqlite3.Connection`（row_factory=Row、foreign_keys ON、`check_same_thread=False`）、`init_db(conn)`（schema.sql を流す。何度呼んでもよい）
- 患者: `create_patient(conn, regimen, patient_id=None) -> str`, `get_patient(conn, pid) -> dict | None`, `list_patients(conn) -> list[dict]`
- コース: `upsert_course(conn, course: Course) -> Course`, `list_courses(conn, pid) -> list[Course]`（course_no 昇順）
- 記録: `add_entry(conn, pid, entry: EntryCreate, recorded_at: datetime, skill_version: str) -> Entry`, `list_entries(conn, pid, start: date | None = None, end: date | None = None) -> list[Entry]`（recorded_at 昇順）, `get_entry(conn, entry_id) -> Entry | None`
- 受診: `create_visit(conn, pid, reception_no, visit_date, expires_at, course_no) -> int`, `get_visit(conn, vid) -> dict | None`, `list_visits(conn, statuses: tuple[str, ...] | None = None) -> list[dict]`, `set_visit_status(conn, vid, status, fallback: bool | None = None)`, `save_timeline(conn, vid, timeline: Timeline)`, `get_timeline(conn, vid) -> Timeline | None`, `save_report(conn, vid, html, data: ReportData)`, `get_report(conn, vid) -> tuple[str, ReportData] | None`, `mark_printed(conn, vid)`（reports・timelines を削除し reception_no を NULL、status=printed）, `purge_expired(conn, now: datetime) -> int`（expires_at を過ぎた未印刷の受診に同じ削除をして件数を返す）
- ログ: `add_pipeline_log(conn, run_kind, run_id, event, **fields) -> None`, `list_pipeline_logs(conn, run_kind, run_id) -> list[dict]`
- Skill: `create_skill_change(...) -> int`, `get_skill_change`, `list_skill_changes`, `update_skill_change(conn, id, **fields)`, `save_skill_version(conn, skill_name, version, content, questions: list[Question] | None)`, `get_skill_version(conn, skill_name, version) -> dict | None`, `latest_skill_version(conn, skill_name) -> dict | None`

## 3. コースと Day（W1-course、`tsutae.course`、純関数）
- Day1 = 実投与日。次コースの実投与日の前日までが今コース。次コースが未登録なら `infusion_date + cycle_days - 1` まで（それ以降の記録は、次コース登録まで今コースの Day15, 16… として数える）
- `build_schedule(courses: list[Course], course_no: int, cycle_days: int, pump_removal_day: int | None) -> CourseSchedule`
- `day_of(d: date, schedule: CourseSchedule) -> int | None`（Day1 より前は None。次コース開始日以降も None）
- `course_for_date(courses, d) -> Course | None`、`current_course(courses, today) -> Course | None`（実投与日が today 以前で最大の course_no）、`previous_course(courses, course_no) -> Course | None`
- `grid_days(schedule, until: date | None = None) -> list[int]`（今コース: Day1〜max(cycle_days, until までの日数)。前コース: Day1〜その最終日）
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
- `load_skill(skill_name, skills_dir: Path | None = None)`, `load_regimen_skill(regimen, skills_dir=None) -> RegimenSkill`（FOLFOX→regimen-folfox, CAPOX→regimen-capox）, `load_report_skill(name="report-format-default", skills_dir=None) -> ReportFormatSkill`, `read_skill_text(skill_name, skills_dir=None) -> str`, `skill_path(skill_name, skills_dir=None) -> Path`
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

## 6. 合成データ（W1-synthetic）
- `data/synthetic/*.json` は `SyntheticPatient`、`labels_*.json` は `PatientLabels`（schemas.py）。`tsutae.synthetic` に `load_patient(path)`, `load_labels(path)`, `all_patients()`, `hard_case_counts(labels) -> dict[str, int]`, `validate_dataset() -> list[str]`（問題の一覧。空なら OK）
- デモ患者 `demo_patient.json`（`patient_id: "P-DEMO0001"`, `visit_date: 2026-11-09`, 受付番号 `"A-023"`）:
  - C1 実投与 2026-09-27 ／ C2 予定 2026-10-11・実投与 2026-10-13（延期2日）／ C3 実投与 2026-10-27 → 受診日 11/09 は C3 Day14
  - 毎コース Day3〜5 に「つらくて書けない」、C3 Day5 に下痢の食い違い（クローズ「なし」＋自由記載に下痢）、C3 Day8 に 37.9℃、代理入力1日、回想1件、入力なしの日が数日
  - 一次置換で伏せられる人名・病院名を含む記載が数件、**二次検出に掛かる記載が1件**（辞書にない架空の姓＋さん。D6 デモ用、`expect_unprocessed: true`）
- 評価用 `eval_patient_a.json` / `eval_patient_b.json`: 各2コース、デモとは別の人・別のパターン
- 自由記載は全体で約60件。**全ての自由記載に正解ラベル**（暦日・Day・用語・status・食い違い・引用）。難ケース4種（`contradiction` / `mild_improving` / `relative_time` / `negation`）をそれぞれ複数件。相対時間は「点滴の次の日から」「先週木曜まで」「ポンプを外した日」を必ず含む
- `source_quote` は**一次置換後**の自由記載に部分一致すること（テストで検査）
- 用語は `backend/tsutae/data/ctcae_terms.json`: `[{"term": "下痢", "en": "Diarrhea", "question_key": "diarrhea"}, …]`（CTCAE v5.0 日本語訳 JCOG 版の有害事象名を約30語。出典「有害事象共通用語規準 v5.0 日本語訳JCOG版より引用」をファイル内 `source` に）。ラベルの term はこの一覧から選ぶ

## 7. 変換パイプライン（W2、要点のみ。詳細は W2 で確定）
- 入力 `PipelineInput`（伏せ字済み・通し番号・コース日程のみ。**仮名ID・受付番号は入れない**）
- 主エージェント（`claude-opus-5-5`）が `agents=` のサブエージェント3役（`claude-sonnet-5-5`）を呼ぶ。**サブエージェントはツールを持たず JSON テキストを返す**。主エージェントがそれをまとめて `mcp__tsutae__emit_timeline` → `mcp__tsutae__emit_report` を呼ぶ（Hook H2 はここに掛ける）
- `AgentRunner` プロトコルを挟み、テストは偽の runner で行う（ツールのハンドラと Hook を直接呼ぶ）
- Hook: H1 `UserPromptSubmit`（`detect_identifiers` でプロンプト全体を検査、`decision: "block"`）／H2 `PreToolUse`（引用の部分一致）／H3 `PreToolUse` Write|Edit（D4 の書き込み先限定）／H4 `PreToolUse`（許可外ツールを deny）。意見のない Hook は `{}` を返す。`HookMatcher(on_failure="block")`
- 失敗・タイムアウト・emit されない → フォールバック（AI変換なし）
- レポート HTML は **`ReportData` から Jinja2 で決定的に描画**。AI は HTML を書かない。AI が決めるのは events・contradictions・per_symptom の選び方だけ

## 8. API（W3、FastAPI。フロントはこの形で作る）
共通: JSON。エラーは `{"error": "<code>"}`（文面ではなくコード。患者画面はコードから `patient_strings.json` のキーを選ぶ）。

### 患者（Cookie `tsutae_pid`）
| メソッド・経路 | 入力 | 出力 |
|---|---|---|
| `POST /api/patient/register` | `{pid}` | `{ok: true}` + Cookie。未知の pid は 404 `{"error":"unknown_patient"}` |
| `GET /api/patient/strings` | — | `patient_strings.json` そのもの |
| `GET /api/patient/{pid}/questions` | — | `{skill_version, questions: Question[]}` |
| `POST /api/patient/{pid}/entries` | `EntryCreate` | `{entry_id, notices: string[]}`（notices は patient_strings のキー。例 `["fixed_rule.fever_38"]`） |
| `GET /api/patient/{pid}/entries` | — | `{entries: [{id, recorded_at, record_date, kind, by_proxy, answers, free_text}]}`（自分の記録のみ。AI の出力は含まない） |
| `POST /api/visit` | `{reception_no}`（Cookie で患者識別） | `{ok: true, message_key: "visit.done"}`。変換はバックグラウンド |

- Cookie の pid と経路の `{pid}` が違えば 403。患者 API のモジュールは `reports`・`timelines`・pipeline を import しない（アーキテクチャテスト）
- 患者画面に出る文字列は `patient_strings.json` と、医師が承認した Skill の質問文だけ

### 医師（Cookie `tsutae_doctor`。`POST /api/doctor/login {password}` で発行、`DOCTOR_PASSWORD` と照合）
| メソッド・経路 | 出力 |
|---|---|
| `POST /api/doctor/login` / `POST /api/doctor/logout` | `{ok}` |
| `GET /api/doctor/patients` | `{patients: [{id, regimen, created_at, register_url}]}` |
| `POST /api/doctor/patients {regimen}` | `{id, register_url}`（register_url = `{public_base_url}/register?pid=<id>`、QR はフロントで描く） |
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

## 9. フロント（W1 骨組み → W4 画面）
- React 18 + Vite 5 + TypeScript + react-router 6。vitest + Testing Library（jsdom）。Prettier（2 スペース、セミコロンあり）
- 開発時は Vite の proxy で `/api` → `http://localhost:8000`
- ルート: 患者 `/register` `/today` `/history` `/visit`、医師 `/doctor/login` `/doctor`（印刷待ち） `/doctor/patients` `/doctor/patients/:pid` `/doctor/settings` `/doctor/pipeline/:visitId` `/doctor/unprocessed/:visitId`
- 患者画面の文字列は `usePatientStrings().t(key)` からのみ出す（直書きしない。テストで検査）。質問文は API の `questions[].text`
- 型は `src/api/types.ts`（schemas.py の API に出る部分を写す）、呼び出しは `src/api/patient.ts` `src/api/doctor.ts`

## 10. 時計・デモ
- `TSUTAE_TODAY=2026-11-09` でデモの「今日」を固定。`scripts/seed_demo.py` が合成データを DB に入れる（W3）

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
- 接続はリクエスト（またはバックグラウンドでの1回の生成）ごとに開く。WAL モード
- `connect(path: Path) -> sqlite3.Connection`（row_factory=Row、foreign_keys ON、`check_same_thread=False`）、`init_db(conn)`（schema.sql を流す。何度呼んでもよい）
- 患者: `create_patient(conn, regimen, patient_id=None) -> str`, `get_patient(conn, pid) -> dict | None`, `list_patients(conn) -> list[dict]`
- コース: `upsert_course(conn, course: Course) -> Course`, `list_courses(conn, pid) -> list[Course]`（course_no 昇順）
- 記録: `add_entry(conn, pid, entry: EntryCreate, recorded_at: datetime, skill_version: str) -> Entry`, `list_entries(conn, pid, start: date | None = None, end: date | None = None) -> list[Entry]`（recorded_at 昇順）, `get_entry(conn, entry_id) -> Entry | None`
- 受診: `create_visit(conn, pid, reception_no, visit_date, expires_at, course_no) -> int`, `get_visit(conn, vid) -> dict | None`, `list_visits(conn, statuses: tuple[str, ...] | None = None) -> list[dict]`, `set_visit_status(conn, vid, status, fallback: bool | None = None)`, `save_timeline(conn, vid, timeline: Timeline)`, `get_timeline(conn, vid) -> Timeline | None`, `save_report(conn, vid, html, data: ReportData)`, `get_report(conn, vid) -> tuple[str, ReportData] | None`, `mark_printed(conn, vid)`（reports・timelines を削除し reception_no を NULL、status=printed。printed への変更はこの関数だけで、`set_visit_status` は printed を受け付けない。印刷済みの受診への `save_*` は `VisitClosedError`）, `purge_expired(conn, now: datetime) -> int`（expires_at を過ぎた未印刷の受診に同じ削除をして件数を返す）
- ログ: `add_pipeline_log(conn, run_kind, run_id, event, **fields) -> None`, `list_pipeline_logs(conn, run_kind, run_id) -> list[dict]`
- Skill: `create_skill_change(...) -> int`, `get_skill_change`, `list_skill_changes`, `update_skill_change(conn, id, **fields)`, `save_skill_version(conn, skill_name, version, content, questions: list[Question] | None)`, `get_skill_version(conn, skill_name, version) -> dict | None`, `latest_skill_version(conn, skill_name) -> dict | None`

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

`convert` の手順: ①入力の記録が0件なら Claude を呼ばず空の Timeline（unprocessed だけ）で成功 ②コードで `detect_identifiers(prompt)` → 掛かれば `error_code="h1_blocked"` でフォールバック ③`asyncio.wait_for(runner.run(...), settings.pipeline_timeout_s)` ④`TimeoutError`→`timeout`、`ClaudeSDKError`（`ResultError` を含む）→ メッセージに max turns があれば `max_turns`、他は `sdk_error`、emit_timeline が来ない→`no_timeline` ⑤成功なら `ConversionResult(timeline（unprocessed を足す）, picks, fallback=False, stats)`。例外の本文はログに入れない（コードだけ）。

ClaudeAgentOptions の要点: `cwd=str(SKILLS_HOME)`, `setting_sources=["project"]`, `skills=[<regimen skill>, "report-format-default"]`, `model=settings.model`, `agents=build_agents(...)`, `mcp_servers={"tsutae": build_server(collector)}`, `allowed_tools=["Task", "Agent", "Skill", "mcp__tsutae__emit_timeline", "mcp__tsutae__emit_report"]`, `disallowed_tools=["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Workflow", "Read", "Glob", "Grep"]`, `permission_mode="dontAsk"`, `hooks=build_hooks(...)`, `max_turns=settings.pipeline_max_turns`, `max_budget_usd=settings.pipeline_max_budget_usd`, `system_prompt=SYSTEM_PROMPT`。

主エージェントの手順（SYSTEM_PROMPT と build_prompt に書く）: Skill（regimen と report-format）を読む → 3役を `Agent` ツールで呼ぶ（date-normalizer と contradiction-finder、その後 term-mapper。並行でよい）→ 結果をまとめ `emit_timeline`（events, contradictions）→ report-format に従い `emit_report`（per_symptom）。Grade・重さの語・助言・原因の推測を出さない。欠けた日を埋めない。食い違いを解決しない。

**W2b の決定（2026-11-03、上より優先）**
- `prepare_input(..., exclude_literals: Sequence[str] = ())`: 自由記載に `exclude_literals`（service が渡す仮名ID・受付番号。NFKC＋casefold で比べる、空文字は無視）を含む記録は外し `UnprocessedEntry(reason="known_identifier")`。自由記載の正規化は `masking.check_text` に任せる（pipeline 側で改行を空白にしない。`masked_texts` は改行を含みうる）
- 範囲外（今コースの Day1 より前・最終日より後・visit_date より後）の記録は**黙って外す**（`UnprocessedEntry` にしない。unprocessed は「伏せ字漏れの疑い・識別子を含む」の意味だけ）。件数はログに `out_of_range_count` で残す
- 自由記載の記録が1件も無い（`masked_texts` が空）なら Claude を呼ばず、空の Timeline（events・contradictions とも空、unprocessed だけ）で成功
- `emit_timeline` の検査: event の `date` はその記録の記録日以前。`day` は `course.day_of(date, schedule, courses=...)` と一致（None ならば None のみ）。同じ (entry_no, term, date, status, source_quote) の重複・同じ食い違いの重複は拒否
- `emit_report` の検査: 受け付けた timeline の present/improving の term ごとに per_symptom の行がちょうど1つ、開始 Day の早い順（同じなら term 名順）。行の欠け・余分・順序違いは拒否（理由は番号と短いコード）
- `convert` が想定外の例外で `internal_error` にするとき、例外の**型名だけ**をログ（`error_type`）に残す


## 7b. レポート（W2-report、`tsutae.report`）

| ファイル | 中身 |
|---|---|
| `build.py` | `build_report_data(*, reception_no, patient_id, regimen_skill, report_skill, courses, entries, visit_date, prepared, result: ConversionResult, questions_by_version: dict[str, list[Question]]) -> ReportData`。**決定的**（同じ入力なら同じ出力）。下の規則 |
| `render.py` + `templates/report.html.j2` + `templates/report.css` | `render_report_html(data: ReportData, *, questions: list[Question]) -> str`。Jinja2（autoescape）。下の描画規則 |

組み立ての規則:
- header: 記録日数＝記録（too_sick を含む）のある日数、入力なし＝記録の無い日数、つらくて書けない＝too_sick の日数（今コースの Day1〜min(最終日, visit_date)）。延期注記は `course.delay_note`。`fallback` は `result.fallback`
- attention（この順）: 食い違い（timeline.contradictions）／`fever_attention_celsius` 以上の体温（今コース）／つらくて書けない（今コース。前コースの同じ Day も too_sick なら `previous_course_same_day=True`）／未処理の記録（count のみ）
- grid: 今コースの行（質問ごと）＋体温行（`show_temperature_row`）＋ `show_previous_course` なら前コースの行（**クローズ回答のみ**、AI の結果を使わない）。セル state: その日の記録の回答＝none/present/hard、記録が無い＝no_input、その日の記録の skill_version の質問集にその質問が無い＝not_asked、too_sick だけの日＝too_sick。同じ日に複数の回答があれば重い方（hard > present > none）。free_text_mark は今コースの events（status が present か improving、question_key 一致、event の date のその Day）、recalled_mark はその event が recalled。列: by_proxy の記録がある日は「代」、too_sick の日は斜線
- per_symptom: `result.picks.per_symptom`（無ければ空）
- quotes: 伏せ字後の自由記載（`prepared.masked_texts`）を Day 順に、`quotes_max_items` まで。未処理の記録は載せない
- フォールバック（`result.timeline is None`）: free_text_mark なし・食い違いなし・per_symptom 空。経過表と引用は同じ

描画の規則: A4 一枚・モノクロ（`@page { size: A4; margin: 10mm }`、`@media print`）。セル: なし=薄い「−」、ある=網掛け、つらい=濃い網掛け、入力なし=空白、未設問=「−−」、つらくて書けない=列全体の斜線、○・「回」・列頭「代」、凡例を欄外に固定。冒頭に「症例は全て合成」、fallback なら「AI変換なし」。用語の欄外に「有害事象共通用語規準 v5.0 日本語訳JCOG版より引用」。low_confidence_threshold 未満の per_symptom は「？」。**Grade・軽症・中等症・重症・重篤などの語を出さない**（テストで検査）。引用が多く溢れる場合は引用欄を2枚目に回す（`page-break-before`）

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
| `GET /api/patient/{pid}/questions` | — | `{skill_version, questions: Question[]}` |
| `POST /api/patient/{pid}/entries` | `EntryCreate` | `{entry_id, notices: string[]}`（notices は patient_strings のキー。例 `["fixed_rule.fever_38"]`） |
| `GET /api/patient/{pid}/entries` | — | `{entries: [{id, recorded_at, record_date, kind, by_proxy, skill_version, answers: [{question_key, value, temperature, question_text}], free_text}]}`（自分の記録のみ。AI の出力は含まない。`question_text` はその記録の skill_version の質問集の文で、見つからなければ null。フロントは null のとき `history.previous_question` を出す） |
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
| `api/deps.py` | W3-api | 接続はリクエストごと（`Depends` で開いて閉じる）。患者 Cookie `tsutae_pid`、医師 Cookie `tsutae_doctor`（値は発行時刻＋HMAC-SHA256(secret_key)。12時間で失効。標準ライブラリの `hmac` で作る）。どちらも HttpOnly・SameSite=Lax。エラーは `{"error": code}`（401 `not_logged_in`・403 `forbidden`・404 `not_found`・422 `invalid_input`）。`RequestValidationError` も `{"error":"invalid_input"}` に変える（入力の文面を返さない） |
| `api/patient.py` | W3-api | §8 の患者 API。**`tsutae.pipeline`・`tsutae.report`・`get_timeline`・`get_report` を import しない**。質問集は `skills.load_regimen_skill`、記録の `question_text` は `db.get_skill_version` の `questions_json` から引く。notices は `api/fixed_rules.py` の純関数 `notices_for(entry: EntryCreate, skill: RegimenSkill) -> list[str]`（体温 ≥ threshold で `patient_string_key`。コードの比較だけ） |
| `api/visit.py` | W3-api | `POST /api/visit`: Cookie の患者で visit を作る（`expires_at = now + report_ttl_hours`、course_no は今コース、status=generating）→ `BackgroundTasks` で新しい接続を開き `generate_visit_report` を呼ぶ。受付番号は NFKC → 前後の空白除去だけで正規化し 1〜32 字（大文字化・ハイフンの統一はしない）。approve の応答 `new_version` は必須（reject は `{ok: true}` のみ）。自由記載が長すぎるときの患者向けキーは `today.free_text_too_long`。今コースが無ければ 409 `{"error":"no_course"}` |
| `api/doctor.py` | W3-doctor | §8 の医師 API（skill-changes 以外）。`GET /visits` と `GET /visits/{id}/report` の前に `purge_expired`。レポートは `HTMLResponse` に `Cache-Control: no-store` と `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:`。`POST /courses` は保存前に `validate_courses`（既存＋新規）。events は `{status, events}`（ポーリング） |
| `api/doctor_skills.py` | W3-doctor | `GET /api/doctor/skills`・`POST/GET /api/doctor/skill-changes`・approve・reject。`tsutae.skillchange` を呼ぶ |
| `skillchange/`（`editor.py` `service.py` `diff.py`） | W3-skillchange | 下の 9b |
| `scripts/seed_demo.py` | W3-api | `python scripts/seed_demo.py [--db PATH]`: 合成3人（`tsutae.dataset`）とコース・記録を入れ、`ensure_skill_versions`。既にいる患者は飛ばす（**DB を消さない**） |
| `tests/test_api_*.py` `tests/test_architecture.py` | 各担当 | `fastapi.testclient.TestClient`。runner は `pipeline_fakes.FakeRunner`、editor は偽物。アーキテクチャテストは `ast` で `api/patient.py` の import を検査 |

### 9b. Skill の書き換え（W3-skillchange、`tsutae.skillchange`）
- `SkillEditor` プロトコル: `async edit(work_root: Path, skill_name: str, request_text: str) -> RunStats`。`SdkSkillEditor` は `claude_agent_sdk.query`（`cwd=work_root`、`setting_sources=["project"]`、`allowed_tools=["Read","Edit","Write"]`、`disallowed_tools` に Bash・Web 系・Task/Agent、`permission_mode="acceptEdits"`、hooks は H1（依頼文の二次検出）・H3（`make_h3(work_root, logger)`）・H4、`max_turns` は 12、`model=settings.model`）。依頼文の H1 に掛かれば編集せず `failed`（`h1_blocked`）
- `request_change(conn, skill_name, request_text, *, editor, settings, skills_home) -> int`: 名前を `SKILL_NAME_PATTERN` で検査 → `skill_changes` を作る → `skills_home/.claude/skills/<name>/SKILL.md` だけを一時ディレクトリ（`tempfile.mkdtemp`）の同じ相対位置に写す → editor → 写しを読み `validate_skill_text` → **version は元のまま**であること（エージェントに上げさせない。変わっていれば元に戻してから比べる）→ `diff.unified(old, new)`（空なら `failed`・`no_change`）→ `pending`（diff・new_text を保存）。どこで失敗しても `failed` と短い error_code。一時ディレクトリは必ず消す。本体には触らない
- `approve_change(conn, change_id, *, skills_home) -> int`: pending のみ。`base_version` が今の版と違えば `failed`・`stale`。new_text の frontmatter の version を base+1 にして再検証 → 本体へ原子的に書く（同じディレクトリの一時ファイル → `os.replace`）→ `save_skill_version` → approved。**git commit はしない**（版の履歴は `skill_versions` に残す）
- `reject_change(conn, change_id) -> None`: pending のみ rejected
- ログは `PipelineLogger(conn, "skill_change", change_id)`（文面なし）

## 9. フロント（W1 骨組み → W4 画面）
- React 18 + Vite 5 + TypeScript + react-router 6。vitest + Testing Library（jsdom）。Prettier（2 スペース、セミコロンあり）
- 開発時は Vite の proxy で `/api` → `http://localhost:8000`
- ルート: 患者 `/register` `/today` `/history` `/visit`、医師 `/doctor/login` `/doctor`（印刷待ち） `/doctor/patients` `/doctor/patients/:pid` `/doctor/settings` `/doctor/pipeline/:visitId` `/doctor/unprocessed/:visitId`
- 患者画面の文字列は `usePatientStrings().t(key)` からのみ出す（直書きしない。テストで検査）。質問文は API の `questions[].text`
- 型は `src/api/types.ts`（schemas.py の API に出る部分を写す）、呼び出しは `src/api/patient.ts` `src/api/doctor.ts`
- **W2b の決定**: 患者 API・医師 API の 2xx 応答は実行時に形を検査し、違えば `error.network` 相当の表示にする（真っ白にしない）。患者側・医師側とも ErrorBoundary を置く。患者画面の直書き検査は「患者のファイルの文字列リテラルに日本語を含めない」「JSX のテキストに英字を書かない」の2つ（変数経由の英字は検査の外。既知の限界として README に書く）。Skill 変更の差分が空なら失敗として扱い承認させない。`Course.note` は200字まで（schemas.py で強制）

## 10. 時計・デモ
- `TSUTAE_TODAY=2026-11-09` でデモの「今日」を固定。`scripts/seed_demo.py` が合成データを DB に入れる（W3）

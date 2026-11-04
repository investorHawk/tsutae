# D4「レジメン」の作り直し — 方針とタスク（2026-11-04 決定）

先生の提案（左に Skill のフォーム、右に Claude とのチャット）をもとに、モックを実際に
操作して固めた方針。実装は opus-implementer。提出は 2026-11-08（日）20:00。

- モック: https://claude.ai/artifact/MV3kPC2RVCkhJbq5QyAWqe（1 枚目を Play で通しで操作できる）。
  同じものを `docs/reference/d4-regimen-mock.dc.html` に置いた（画面の文言・状態の色・
  操作の順はこれが正）
- 判断の記録: `docs/decisions.md`「D4 レジメンの作り直し（2026-11-04）」
- 旧 D4（一文 → 差分 → 承認）は**レポートの形式（report-format）にだけ残す**。
  レジメンはこの画面に移す

## 1. 方針（なぜこの形か）

| 決めたこと | 理由 |
|---|---|
| **左のフォームが正本。SKILL.md はフォームの値からコードが決まった形（Jinja2）で描く。Claude に SKILL.md を書かせない** | レポートを `ReportData` から決定的に描くのと同じ考え。H3（書き込み先の制限）が要らなくなり、今より安全。FOLFOX/CAPOX の SKILL.md の差は 63 行で全て「型のある部分」（日数・薬・日付の言い方・用語と質問）だった |
| **Claude が触るのは欄の値だけ。専用ツール（`set_fields` / `ask` / `propose_questions`）で返し、pydantic で検査する** | `emit_timeline` と同じ作り。自由文を解釈して欄に入れる処理をコードに持たない |
| **チャットは「1 回送ると 1 回答える」。応答中は左の欄を編集できない** | 医師の入力と Claude の書き換えがぶつからない。長く待つ状態・取り残しが起きない（`AskUserQuestion` で止めて待つ方式は採らない） |
| **Claude が入れた値には出どころを持たせる**: 先生の文から（青）／標準の値から（橙の点線・未確認）。先生が直接入れた欄は、先生が頼まない限り Claude は書き換えない | 先生の判断「標準の値も入れてよい」を、確かめる手順とセットにする |
| **採用の前に「AI が入れた値」を一括で一覧し、チェック 1 回で確かめる。一覧の行ごとに「削除」が付く** | 欄ごとの確認は 30 回押すことになり重かった（モックで確認）。不要な候補はその場で落とせる |
| **既存レジメンを開いて欄を直接直しても、チャットで頼んでも、「版 N+1 の下書き」になる。採用まで患者の画面は変わらない。変わるのは次の記録から** | 今の版の扱いと同じ。差分は版 N との unified diff で見せる |
| **質問の「部品集」を DB に持つ**（初期値は今の 6 問。採用した新しい質問は部品集にも入る）。選ぶのは画面内の小窓 | 短い名前（label）を部品に持たせるので、医師画面に `tearing` のような key がそのまま出ない |
| **FOLFOX/CAPOX の 2 つ固定を外す**（`Regimen` 型・`REGIMEN_SKILL_NAMES`・`REGIMENS`・`schema.sql` の CHECK・患者登録の選択肢） | DB は表を作り直して行を移す（先生の判断。既存の合成データは残す） |
| 薬の量（mg/m² など）は持たない | 変換に要らず、誤りの害が大きい（先生の判断） |
| **補足の指示（自由記載）の欄を 1 つ持ち、本文の末尾の節に描く** | 今の一文 D4 で本文を直せていた受け皿。型に入らない施設の決まりを失わない |

### 画面の流れ（モックのとおり）

```
タブ: FOLFOX 版1 | CAPOX 版1 | ＋ 新しいレジメン
左: 基本（名前・対象・1コースの日数）／投与スケジュール（薬・経路・Day・内服の回数・飲み始めや抜去）＋ Day の帯
    ／副作用（患者の言い方・CTCAE の用語・対応する質問）／患者への質問（短い名前・文・型。38.0℃ の固定規則は外せない）
    ／補足の指示（自由記載）
右: チャット（固定表示・自動で下へ）。Claude は「変えた欄」を押せる札で示し、迷ったら 1 問ずつ選択肢つきで聞く
    （選択肢・チャットの文・赤枠の欄への直接入力のどれでも答えになる）
下: 確認へ進む（未入力 0 で押せる）／下書きを捨てる
確認: AI が入れた値の一覧（行ごとに削除・チェック 1 回）→ SKILL.md（新規は全文、既存は版 N との差分）→ 患者のスマホの見本 → 採用
```

欄の状態の色（色だけに頼らず文字も添える）: 未入力 = ピンク（必須）／Claude が聞いています = 赤枠／
AI が入れた = 橙の点線（採用の前に確かめる）／先生が入れた = 青枠。

## 2. 壊してはいけないこと（既存の決まりとの整合）

- 患者に届くのは**採用された質問文**だけ。Claude の文は院内の画面（チャット）にだけ出る
- 先生のチャットの文は毎回 H1（`detect_identifiers`）を通す。掛かれば送らず 400 を返す
- チャットの文面は DB の下書きに置く（院内だけ）。ログ（`PipelineLogger`）には種類と回数だけ残し、文面を入れない
- エージェントは Read/Edit/Write を持たない（H4 は専用ツールだけ許す）。`--no-session-persistence`・`setting_sources=[]` は今のまま
- `regimen-folfox@1` / `regimen-capox@1` は評価済みの版。**同じ描き方で描くと今の SKILL.md と一致する**テストを置き、版は上げない
- 採用でアプリは git commit をしない。版の履歴は `skill_versions` に全文

## 3. タスク（opus-implementer。全て TDD）

優先順に並べた。**T90 → T91 → T93 → T94 → T96 の縦の一本**（新しいレジメンをチャットで作って採用できる）を
先に通し、T92・T95・T97 を重ねる。間に合わないときに落とす順は §4。

| ID | タスク | 完了条件 | 依存 |
|---|---|---|---|
| T90 | 仕様と設計の更新: `spec.md` D4 の項（レジメンは新画面、形式は一文のまま）・H3/H4 の記述、`architecture.md` §9c（下書き・部品集・1 往復の契約）、`decisions.md` は記入済み | 先生が差分を見て OK | — |
| T91 | **フォーム → SKILL.md の描画**: `RegimenForm`（pydantic。基本・薬・副作用・質問・補足）と Jinja2 テンプレート。`render_regimen_skill(form) -> str`。FOLFOX/CAPOX の値を `backend/tsutae/skills/regimen_forms/` に置く | `render(folfox_form) == 今の regimen-folfox/SKILL.md`（capox も）がバイト一致。`validate_skill_text` を通る。日付の言い方の表は薬の表から導く | — |
| T92 | **部品集**: `question_library` 表（key・label・text・answer_type・出どころ）、初期 6 問の seed、`GET/POST/DELETE /api/doctor/question-library` | 初期 6 問が入り、追加・削除できる。key の重複と H1 に掛かる key/text を拒否 | T10 |
| T93 | **下書きと採用**: `regimen_drafts` 表（regimen 名・もとにした Skill と版・form JSON・欄ごとの出どころ・チャット・状態）、`POST /regimen-drafts`（新規 or 既存から）、`PATCH .../fields`（直接編集。応答中は 409）、`POST .../discard`、`GET .../preview`（SKILL.md 全文 or 版 N との diff・患者見本・検査結果）、`POST .../adopt`（新規: Skill フォルダ作成＋`skill_versions` 版 1、既存: 版 N+1） | 採用後 `load_regimen_skill` で読める。既存の記録は当時の版で表示される（既存テストが通る）。adopt は「AI が入れた値の確認済み」フラグが無ければ 409 | T91 |
| T94 | **Claude の 1 往復**: `POST .../turns {text}`。H1 → Agent SDK `query()`（同一プロセスの MCP ツール `set_fields`・`ask`・`propose_questions`、`allowed_tools` はこの 3 つだけ、H4 で他を deny、`max_turns`・`max_budget_usd`）→ pydantic 検査 → 下書きに反映（先生が入れた欄への書き込みは `overwrite_requested` が無ければ拒否し理由を返す）→ 返答とチャットを保存。依頼文には今のフォーム・直近の会話・部品集・CTCAE の一覧・「先生の文に無い値は標準の値として `source=standard` を付ける」を入れる | 偽の query で: 欄が埋まる／`ask` が欄 id と選択肢を返す／先生の欄が守られる／H1 で止まる／時間切れで failed。ログに文面が無い | T92, T93 |
| T95 | **2 レジメン固定の解除**: `schemas.Regimen` を str にし読み込んだ Skill と照合、`REGIMEN_SKILL_NAMES` を frontmatter から、`repo_patients.REGIMENS`、`schema.sql` の CHECK を外す移行（表を作り直して行を移す。起動時に 1 回）、`api/doctor.py`、フロントの `Regimen` 型と `PatientCreateForm`（API から一覧）、医師画面の短い名前は部品集の label から | 既存 DB（CHECK あり）を起動で移行し全行が残るテスト。SOX の患者を登録して記録 → 受診 → レポートまで通る（API を呼ばない構成） | T93 |
| T96 | **画面 D4 レジメン**（`frontend/src/pages/doctor/Settings.tsx` を分割）: タブ／左フォーム 5 節＋Day の帯／欄の 4 状態／右チャット（固定・自動スクロール・応答中の表示・変えた欄の札・選択肢）／下のバー／確認（AI 一覧＋行の削除＋チェック・SKILL.md or diff・スマホ見本）／登録済み／部品集の小窓／CAPOX の切り替え／直接編集 → 版 N+1 | モックの 2 本の流れ（新規・既存の直接編集）が vitest で通る。IME 変換中の Enter で送らない | T93, T94 |
| T97 | **通しと記録**: `scripts/run_demo_regimen.py`（本物の Claude で SOX を 1 往復。先生が `!` で実行）、ブラウザ通し、`docs/decisions.md` に実測（費用・秒・拒否回数）、`demo-script.md`、README の D4 の説明と画像、テスト件数 | smoke が OK。README の数値は実測だけ | T96 |

## 4. 範囲（先生の判断 2026-11-04 夜: **落とさず全部作る**）

T90〜T97 を全て作る。補足の指示（自由記載）の欄も持たせる。実装の途中で間に合わないと分かったときは、
勝手に削らず先生に確認する。そのときの候補の順（参考）: 部品集の小窓 → 既存の直接編集 → 補足の指示欄 →
CAPOX の切り替え。どの場合も **T91 のバイト一致テスト・H1・採用前の確認** は落とさない。

## 5. 先生にしか決められないこと（残り）

- デモで足すレジメンの名前と内容（モックは SOX の例。合成なら何でもよい）
- T90 の spec 差分の承認

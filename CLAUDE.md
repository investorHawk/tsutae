<!--
保守メモ（Claude には渡らない）: アプリの変換エージェントは cwd=backend/skills_home・
setting_sources=["project"] で動き、祖先のこのファイルも読みうる。
backend/tsutae/pipeline/orchestrator.py の NO_CLAUDE_MD_ENV
（CLAUDE_CODE_DISABLE_CLAUDE_MDS=1）で止めている。外すとこの文面が患者記録の変換に混ざる。
-->

# tsutae

Built with Claude (Code): Japan 2026 の提出作品。提出期限は 2026-11-08（日）20:00 JST。
症例は全て合成で、実患者のデータは使わない。ユーザーは「先生」と呼ぶ。

## 大会の決まり（グローバル設定より優先）

- 実装は全て Claude が書く（自分か opus-implementer）。sol-implementer / Codex CLI は
  読み取り専用のレビューにだけ使う。`docs/plan.md` の「フロントは sol に並列で」は古い
- 他のリポジトリのコードはコピーしない。仕様を読むのはよいが、ここで書き直す
- 大会は「Claude で作ったこと」が評価の対象。判断は `docs/decisions.md` に表で残す

## コマンド

`make` はサンドボックス内で落ちるので、エージェントは scripts を直接呼ぶ。

| 目的 | コマンド |
|---|---|
| 全テスト（backend + frontend、README のテスト件数も更新） | `scripts/test.sh` |
| backend の一部だけ | `scripts/test.sh backend/tests/test_course.py -q` |
| frontend の一部だけ | `cd frontend && npx vitest run src/<path>` |
| lint（ruff・black --check・prettier --check） | `scripts/lint.sh` |
| 整形 | `scripts/format.sh` |
| 動画（Remotion）のテスト・lint | `cd video && npm test` / `npm run lint` |

API を呼ぶものはサンドボックス外で先生が実行する: `! make smoke`、`! make eval`、
`! .venv/bin/python scripts/run_demo_visit.py`。API を呼ぶテストはキーが無いと skip される。

コミットの前に `scripts/lint.sh` と `scripts/test.sh` を通す。全テストが README の件数を
書き換えるので、その差分も同じコミットに入れる。

## サンドボックスの制約

- `.env` は読めない（stat も拒否）。pytest は `backend/pytest.ini`（rootdir=backend）で走らせ、
  リポジトリ直下を走査させない
- `uv` は落ちる。依存は `.venv/bin/pip` で入れる（`allowed_domains` に pypi.org と
  files.pythonhosted.org）
- リポジトリ直下の `.claude/skills/` には書けない。アプリの Skill は
  `backend/skills_home/.claude/skills/<name>/SKILL.md`
- codex は `dangerouslyDisableSandbox: true` でしか起動しない。必ず `-s read-only` で使う

## 壊してはいけない設計

- 患者のスマホに AI の文を出さない。AI の出力は院内の画面と紙にだけ出す
- レポートの HTML は `ReportData` から Jinja2 で決まった形に描く。AI に HTML を書かせない
- 自由記載は伏せ字（一次置換＋二次検出）を通ってから Claude に送る。二次で疑いが出た記録は
  送らずに D6（未処理）へ回す
- 変換の会話を `~/.claude/projects/` に残さない（`no-session-persistence`）。開発用の
  CLAUDE.md も変換に入れない（`NO_CLAUDE_MD_ENV`）
- Hook H1〜H4 と許可ツールの一覧は、テストで値まで固定している。変えるときはテストと
  `docs/decisions.md` を一緒に直す
- 評価の数字（`docs/eval/`）は実測だけを書く。README の数値もそこから写す

## 資料

- 仕様: `docs/spec.md`（v1.0 承認済み。変えるときは先生に確認する）
- 判断の記録: `docs/decisions.md`／構成: `docs/architecture.md`
- 日程とタスク: `docs/plan.md`・`docs/tasks.md`／デモ: `docs/demo-script.md`
- 審査員の目で見た改善点: `docs/review-judge-2026-11-04.md`

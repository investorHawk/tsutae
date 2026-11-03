# つたえ — 症例は全て合成です（デモ・評価に実患者のデータは一切使っていません）

外来化学療法（FOLFOX/CAPOX）中の消化器がん患者が毎日スマホで記録し、受診時に院内QRを読むと、Claude が記録を「暦日・コース日数・標準用語・原文引用」つきの時系列に直し、**医師が決めた形式の A4 一枚**として診察室に届けるアプリです。患者のスマホに AI の文は出ません。

> Built with Claude (Code): Japan 2026 提出作品（ソロ、期間中の新規制作）。現在は**仕様策定段階**で、コードはまだありません。

## 状態

| 項目 | 値 |
|---|---|
| 仕様 | `docs/spec.md`（v1.0、2026-11-03 承認） |
| テスト件数 | 669件 通過 / 全669件（backend 669/669、frontend 0/0。`make test` が自動更新。API を呼ぶテストはキーが無いと skip） |
| 精度評価 | 未実施（`docs/eval/` に実測値と失敗例を残す予定） |

## なぜ作るか（執筆予定）
- 誰が、どの場面で、どれくらい困っているか
- 聞き取り 約3分 → 約30秒（実感値、未測定）

## 既存品（Juno、国内 ePRO）との違い（執筆予定）
`docs/spec.md` 14節の比較表をここに置く。

## なぜ紙か（執筆予定）
電子カルテ連携なしで医師の手元に届く。患者は AI の文を見ない。

## AI がしないこと
`docs/spec.md` 12節。重さの判定・トリアージ・患者への助言・欠けた記録の補完・食い違いの解決をしない。

## 患者情報の扱い
`docs/spec.md` 13節。氏名・生年月日を集めない。自由記載は伏せ字にしてから Claude に送る。検出漏れはゼロにできない。

## Claude の使い方（執筆予定）
Claude Agent SDK 上の変換パイプライン: サブエージェント3役、Hook 4本、Skill 3本。医師が自然言語で Skill を書き換えるループ。

## 動かし方（開発）
- Python 3.12 の venv: `.venv`（`uv python install 3.12` 後に `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"`、または `uv sync`）
- フロント: `cd frontend && npm install`
- テスト / lint: `make test` / `make lint`
- 環境変数（`.env` に書く）: `ANTHROPIC_API_KEY`（必須）、`DOCTOR_PASSWORD`（医師画面のパスワード、既定 `demo-doctor`）、`TSUTAE_SECRET`、`TSUTAE_TODAY`（デモ用に「今日」を固定。例 `2026-11-09`）
- Agent SDK の動作確認: `make smoke`／精度評価: `make eval`（API を呼ぶ）

## 文書
- 仕様: `docs/spec.md`
- 決めたことと理由: `docs/decisions.md`
- 日程: `docs/plan.md`
- タスク: `docs/tasks.md`
- 実装の契約: `docs/architecture.md`
- 企画（正本）: `docs/reference/concept.md`

## 出典・利用条件
- 有害事象の用語名は「有害事象共通用語規準 v5.0 日本語訳JCOG版より引用」。非営利利用の範囲で使用。営利利用は JCOG との別契約が必要
- PRO-CTCAE の文言は使用していない（項目分類のみ参考）

## ライセンス
未定（公開リポジトリ化の際に決める）

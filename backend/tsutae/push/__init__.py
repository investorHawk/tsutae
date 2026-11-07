"""毎日の通知（docs/plan-device-records.md §4）。

- `decide`: 送るかどうかの判定（純関数）
- `payload`: 通知の本文（patient_strings.json の固定文だけ）
- `sender`: VAPID の鍵の読み込みと、pywebpush で送る処理
- `dispatch`: 対象を探して送る1回分（DB を読み書きする）

変換結果（reports・timelines）と D4 の下書き（regimen_drafts）を読まない（アーキテクチャテスト）。
"""

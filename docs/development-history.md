# 開発の経緯

開発の流れを、後から一枚にまとめたものです。Claude Code が 2026-11-08 に、コミットの履歴・PR・`docs/decisions.md` から書きました。記録に無いことは書いていません。判断の理由と細かい経過は [`docs/decisions.md`](decisions.md) が正本です。

数字はコミット `859fd3d`（PR #10 の merge）の時点のものです。

| 項目 | 数 |
|---|---|
| 期間 | 2026-11-03 18:06 〜 2026-11-08 01:03（JST） |
| コミット | 183 件（うち merge 16 件） |
| PR | 10 件（全て merge 済み） |

## 日ごとの流れ

| 日付 | コミット | 主なこと | PR |
|---|---:|---|---|
| 11/3 | 11 | 仕様書を作り、v1.0 を承認する。提出期限を決め直す。基盤（DB・コース・Skill・伏せ字・合成データ）を作る | |
| 11/4 | 75 | 変換のパイプライン・レポート・API・画面を作って結合する。本物の Claude で確かめ、精度を 2 回測る。実画面を見ながら患者・医師の画面を見直す | [#1](https://github.com/investorHawk/tsutae/pull/1)・[#2](https://github.com/investorHawk/tsutae/pull/2)・[#3](https://github.com/investorHawk/tsutae/pull/3) |
| 11/5 | 19 | レジメンの画面（D4）をフォームとチャットに作り直す。スマホのホーム画面アイコンと全画面表示を足す | [#4](https://github.com/investorHawk/tsutae/pull/4)・[#5](https://github.com/investorHawk/tsutae/pull/5) |
| 11/6 | 62 | D4 を使いやすくし、番号で登録できるようにする。毎日の通知と、記録のスマホ保存を作り、iPhone の実機で確かめる。精度を測り直す。動画を先生の声つきに作り替える | [#6](https://github.com/investorHawk/tsutae/pull/6)・[#7](https://github.com/investorHawk/tsutae/pull/7) |
| 11/7 | 14 | 動画を 175 秒・12 場面に直し、先生の声で仕上げる。README を提出用に整える。アイコンを替える | [#8](https://github.com/investorHawk/tsutae/pull/8)・[#9](https://github.com/investorHawk/tsutae/pull/9) |
| 11/8 | 2 | 動画の通知の場面を新しいアイコンに差し替える | [#10](https://github.com/investorHawk/tsutae/pull/10) |

コミットの数は、コミットに記録された日付で数えています。

## 途中で変えた判断

| いつ | 変える前 | 変えた後 | 理由 | 誰が |
|---|---|---|---|---|
| 11/3 | 提出期限は 11/10 14:00 | 11/8 20:00 に早める。減った日数は、並列の実装と範囲の縮小で補う | 先生の指示 | 先生 |
| 11/4 夜 | D4 のレジメンは一文で頼んで書き換える | 左にフォーム、右に Claude とのチャットの画面にする。SKILL.md はフォームの値からコードで描く | 一文で頼む方式は、Skill の中身が差分でしか見えなかった。モックを実際に操作して確かめた | 先生の提案 |
| 11/5 夜 → 11/6 | 記録はサーバーに保存する。スマホ保存は案として README に書くだけ | 通知を作り、記録はスマホ保存へ完全に移す | 余計なデータをサーバーに持たないため。Claude のおすすめは通知だけだったが、影響を聞いたうえで先生が完全移行を選んだ。実機で動かなければマージしない判定の時刻も決めた | 先生 |
| 11/6 | HTTPS は Tailscale Funnel | Tailscale Serve にする | 先生がリスクを尋ねた。全世界に公開すると、公開リポジトリに載るデモ患者の番号で受付を送られ、Claude の費用がかかる | 先生 |
| 11/5 夜 → 11/6 | 動画に音声を入れない | 先生の声を全編に入れる | 本人の言葉で始めて終える動画になったため | 先生 |
| 11/7 → 11/8 | アイコンは「つ」の文字 | 顔つきの吹き出しにする。動画の通知の場面も撮り直す | もっと可愛らしく、押しやすいものを先生が希望した | 先生 |

## 履歴の見方

- **分岐と merge の形**: GitHub の [Insights の Network](https://github.com/investorHawk/tsutae/network)、または手元で `git log --graph --oneline`
- **main に入った単位**: `git log --first-parent --oneline main`
- **PR の説明文**: [閉じた PR の一覧](https://github.com/investorHawk/tsutae/pulls?q=is%3Apr+is%3Aclosed)

11/6〜11/7 の作業の一部は手元で merge し、PR #8・#9 でまとめて main に入れました。そのため個別の PR はありません。次の merge コミットで、分岐と変更の内容を確かめられます。

| 内容 | merge コミット | main に入った PR |
|---|---|---|
| 毎日の通知とスマホ保存 | [`76b4c92`](https://github.com/investorHawk/tsutae/commit/76b4c92) | #8 |
| 動画を声つきにし、D4 の返答の表示を直す | [`50fbdd0`](https://github.com/investorHawk/tsutae/commit/50fbdd0) | #8 |
| 動画を先生の声で仕上げ、録音アプリを足す | [`48b45e2`](https://github.com/investorHawk/tsutae/commit/48b45e2) | #8 |
| README に作品概要と既存ノートとの違いを足す | [`91d236c`](https://github.com/investorHawk/tsutae/commit/91d236c) | #8 |
| アプリのアイコンを替える | [`d0559f9`](https://github.com/investorHawk/tsutae/commit/d0559f9) | #9 |

## 関連する資料

- 仕様: [`docs/spec.md`](spec.md)
- 決めたことと理由: [`docs/decisions.md`](decisions.md)
- 精度の実測: [`docs/eval/`](eval/)
- Claude の使い方: [README の「Claude の使い方」](../README.md#claude-の使い方)

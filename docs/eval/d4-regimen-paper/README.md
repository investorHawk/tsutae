# D4 で作ったレジメン（RAM＋wPTX）の紙（A4 の印刷の見た目）

T97「ブラウザ通し（28日・質問7問・前コースありで紙が読めるか）」の、機械で確かめられる部分の記録。
症例は全て合成（架空）。API は呼んでいない（偽の AI 変換と、AI 変換なしのフォールバック）。

## 何の紙か

- `backend/tests/test_regimen_paper_flow.py` の通しで作った紙の HTML を、ヘッドレスの Chromium
  （Playwright 同梱の `chrome-headless-shell`）で A4 に印刷した PDF を PNG にしたもの
- レジメン: D4 の API（下書き → 直接編集の PATCH → 確認 → 採用）で採用した RAM＋wPTX（28日。
  質問7問: しびれ／下痢／口内炎／吐き気・食欲／だるさ／出血／体温。しびれ・だるさ・出血は新しい質問）
- 患者: 第1コース（2026-09-15〜10-12）と第2コース（10-13〜。受診日 2026-11-09 が Day28）。
  両コースに患者 API で記録（つらくて書けない・発熱・自由記載を含む）

| ファイル | 中身 |
|---|---|
| `ram-wptx-ai-p1.png` | 偽の AI 変換あり。1枚目（ヘッダ・要確認・経過表・凡例・症状別） |
| `ram-wptx-ai-p2.png` | 同じ紙の2枚目（引用・欄外の注記） |
| `ram-wptx-fallback-p1.png` | AI 変換なし（フォールバック）の1枚目 |

## テストが確かめていること（`test_regimen_paper_flow.py`。機械で）

- 経過表の段・列（Day1〜21・Day22〜28）、各段の今コース・前コースの 7 行と短い名前、ヘッダの
  表示名、自由記載の出来事が足した質問の行につながること、表示名・label のエスケープ
- 紙に出ない文は3つの経路で見る。採用した SKILL.md の本文の行が紙に無いこと。変換の emit に
  余分な自由文の欄（timeline の上・出来事・症状別の行）を足すと `extra="forbid"` で拒否され、
  正しく渡し直した emit だけが紙に出ること。D4 のチャットの Claude の返答・問いの文は下書きの
  会話には出るが、採用した SKILL.md と紙には出ないこと
- A4 に収まるか（はみ出し・重なり）は機械では見ていない。下の目視だけ

## 見たこと（2026-11-05、目視）

- 経過表は 1 段 21 列まで（`grid_view.GRID_MAX_COLS`）なので、28日は Day1〜21 と Day22〜28 の
  2 段に折り返す。1 列は約 8mm（字を詰める `dense`）。横は A4 の本文の幅（190mm）に収まり、
  はみ出し・重なりは無い。2 段目の列の幅は 1 段目とそろい、Day22 が Day1 の真下に来る
- どちらの段にも今コース（第2）と前コース（第1、行名は斜体）の 7 行ずつが出る
- 行の名前は短い名前（新しい質問は form の label: しびれ・だるさ・出血）。質問文は出ない
- ○ は今コースの行だけ（だるさ Day3・しびれ Day9・出血 Day9）。前コースはクローズ回答だけ
- 紙は 2 枚。1 枚目は症状別の欄まで、引用は 2 枚目の頭から（欄の途中では切れない）。
  `render.py` と `report.css` の想定は「通常のコースは A4 1 枚。コースが延びて経過表の段が
  増えたときだけ 2 枚目に流れる」。28日は延びていない普通の受診でも経過表が 2 段になるので、
  その延びたコース向けの 2 枚の仕組みに乗って必ず 2 枚になる（想定の外にある新しい状況。
  FOLFOX の14日・CAPOX の21日は 1 段に収まり 1 枚）。CSS は変えていない
- 1 枚目は症状別の欄で下端の近くまで埋まる。要確認や症状別の行が増えれば、その欄ごと 2 枚目に
  流れる（`break-inside: avoid`。はみ出しではない）
- 前コースの行の列頭の日付は今コースの日付（10/13〜11/9）で、前コースの暦日は紙に無い
  （前からある作り。FOLFOX・CAPOX の前コースも同じ）。例: 第1コース Day20（10/04）の体温
  37.2 は、列頭が「11/1」の列に並ぶ
- 2026-11-06: 用語の説明の文と用語の置き換えに合わせて、`ram-wptx-ai-p1.png`・`-p2.png` を下の手順で作り直した。仮名ID は作るたびに変わる

## 先生に確かめてもらうこと

- **28日の紙が 2 枚になること**: このまま 2 枚でよいか、1 枚に収めるか（収めるなら 1 段の
  列の数・列の幅・字の大きさを変えることになり、FOLFOX・CAPOX の紙と見た目を合わせる判断が
  要る）
- **前コースの行が今コースの日付の列頭の下に並ぶこと**: 28日の紙では前コースの行が長く、
  列頭の日付（今コース）を前コースの日付と読み違えやすい。直すなら最小限は「前コースの
  ブロックの見出しに暦日の範囲（例: 2026-09-15〜10-12）を足す」。この見出しは FOLFOX・CAPOX
  の前コースにも出るので、直すと FOLFOX の紙のバイトとスナップショットも変わる（今は直して
  いない）

## 作り直す手順（先生がサンドボックスの外で実行）

```sh
# 1. 紙の HTML を書き出す（API は呼ばない。サンドボックスの中でもよい）
TSUTAE_PAPER_OUT=$TMPDIR/paper scripts/test.sh backend/tests/test_regimen_paper_flow.py -q
# 2. A4 の PDF に印刷する（Chromium はサンドボックスの中では起動しない）
# 入っている版は ls ~/Library/Caches/ms-playwright | grep chromium_headless_shell で確かめる
CH=~/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell
$CH --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=$TMPDIR/paper/ram_wptx_ai.pdf file://$TMPDIR/paper/ram_wptx_ai.html
```

Chrome.app でもよい: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new
--no-pdf-header-footer --print-to-pdf=… file://…`。

3. PDF の各ページを PNG にする（macOS の PDFKit。2 倍の解像度。このディレクトリの
`pdf2png.swift`）。PDF と PNG の名前は上の表に合わせる:

```sh
swift docs/eval/d4-regimen-paper/pdf2png.swift $TMPDIR/paper/ram_wptx_ai.pdf \
  docs/eval/d4-regimen-paper/ram-wptx-ai            # → ram-wptx-ai-p1.png, -p2.png
```

フォールバックの紙は `ram_wptx_fallback.html` を同じ手順で印刷し、`ram-wptx-fallback` の
1 枚目だけを残す。プレビュー.app で PDF を開き「書き出す…」で PNG にしてもよい
（2 倍の解像度は 144 ピクセル/インチ）。

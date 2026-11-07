# 案 B（DemoB）の声

- 録音は録音アプリで行う: `cd video && npm run voice`（ブラウザが開く。cmux の内蔵ブラウザでも Chrome でも録れる。最初の 1 回だけマイクの許可を求められる）。リハーサルで長さを測り、うまく言えたらそのまま保存できる。保存すると `b01.wav` の名前でここに入る。前の録音は `video/out/voice/old/`、録ったものの控えは `video/out/voice/takes/` に残る
- 録音中に原稿を変えられる。変更後の文は `docs/video/narration-b-edits.json` に入る。字幕には自動で入らないので、録音を終えたら `src/storyboards/b.ts` へ移す
- 場面ごとに 1 本、先生が `docs/video/narration-b.md` の「字幕の文」を読み上げて録る
- ファイル名は場面 id の頭 `b01`〜`b12`＋拡張子（`.m4a` `.mp3` `.wav`）。`b01_intro.m4a` のように `_`・`-` で名前を足してもよい
- 置いた声は場面の頭から 0.3 秒後に鳴る。場面の秒数は変わらないので、場面の秒より短く録る（少し長いぶんは切らずに次の場面に重なる）
- 1 本でも置くと、案 B の BGM は全体で半分の音量になる
- 置いたら `cd video && npm run studio` で確かめる（manifest が書き直されて鳴る）
- 音声ファイルは git に入れない（`.gitignore`）

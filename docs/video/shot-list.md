# 撮影リスト（3 案共通）

生成物: `cd video && npm run docs` で `video/src/footage.ts` と構成データから書き出す。
最低秒は 3 案で使う最長に合わせた値。長い分は動画側で切り詰める。音声は使わない（動画側で消す）。スマホは縦（9:16）、PC は横（16:9）。画面に実在の病院名・人名を入れない。
置いた後に `npm run studio` などを動かすと、manifest（`src/footage.generated.ts`）が書き直されて枠のカードが録画に差し替わる。`F1_patient_today.mp4` のように id の後ろに `_` で名前を付けてもよい（.mov も可）。

| id | 場面 | 端末 | 最低秒 | 撮る内容 | 使う場面 | 置き場所 |
|---|---|---|---|---|---|---|
| F1 `patient_today` | 今日の記録 | スマホ縦（9:16） | 14 | 3 択を 5 問タップ → 体温 → 自由記載に「おとといの夜から口内炎がいたい」と打つ → 保存。家族の代理のチェックも一度見せる | DemoA #3 footage（12 秒）<br>DemoB #4 footage（8 秒）<br>DemoC #3 footage（6 秒） | `video/public/footage/F1.mp4` |
| F2 `patient_too_sick` | つらくて書けない | スマホ縦（9:16） | 6 | ボタンを押す → 確認 → 履歴に「つらくて書けない」が残る | DemoA #4 footage（6 秒）<br>DemoB #4 footage（6 秒）<br>DemoC #3 footage（5 秒） | `video/public/footage/F2.mp4` |
| F3 `patient_fever` | 38.2℃ の案内 | スマホ縦（9:16） | 8 | 体温に 38.2 → 施設の案内文が出る | DemoA #5 footage（8 秒）<br>DemoC #3 footage（7 秒） | `video/public/footage/F3.mp4` |
| F4 `patient_visit` | 受診 | スマホ縦（9:16） | 10 | QR を読む（カメラ越しでも可）→ 受付番号 A-023 → 「先生に届けました」 | DemoA #6 footage（10 秒）<br>DemoB #5 footage（8 秒）<br>DemoC #4 masking（10 秒） | `video/public/footage/F4.mp4` |
| F5 `doctor_visits` | 印刷待ち | PC 横（16:9） | 6 | 一覧 → 印刷ボタン → 印刷ダイアログ | DemoA #8 footage（6 秒） | `video/public/footage/F5.mp4` |
| F6 `printer` | 実機印刷 | カメラ | 6 | プリンタから紙が出る → 手に取る | DemoA #9 footage（6 秒） | `video/public/footage/F6.mp4` |
| F7 `doctor_pipeline` | D5 変換ログ | PC 横（16:9） | 10 | 任意（案 C の pipeline の背景に薄く敷く。無くても成立） | DemoC #5 pipeline（背景（任意・ループ）） | `video/public/footage/F7.mp4` |
| F8 `doctor_settings` | D4 | PC 横（16:9） | 18 | 一文を入力 → 待ち（早送り可）→ 差分 → 承認 → 版が上がる | DemoA #11 footage（14 秒）<br>DemoB #8 footage（12 秒）<br>DemoC #8 footage（12 秒） | `video/public/footage/F8.mp4` |
| F9 `patient_new_question` | 翌日 | スマホ縦（9:16） | 6 | 今日の記録に新しい質問「口の中のことで、食事がとりにくいことはありましたか」が出ている | DemoA #12 footage（6 秒）<br>DemoB #8 footage（6 秒）<br>DemoC #8 footage（6 秒） | `video/public/footage/F9.mp4` |
| F10 `doctor_report` | レポート画面 | PC 横（16:9） | 10 | 任意（report の場面は画像 sample-report.png で描くので無くてよい） | （どの案でも使わない・任意） | `video/public/footage/F10.mp4` |

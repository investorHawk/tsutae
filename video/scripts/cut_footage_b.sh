#!/usr/bin/env bash
# 案 B の録画（先生が 2026-11-08 に iPhone で撮った動画）を、場面の区間の長さに切って
# public/footage/F<n>.mp4 に書く。元の動画は public/private/（git の管理外）に置く。
#
# - 音は全て外す（家族の声が入っているため。-an）
# - 撮影日時・端末・位置などの埋め込み情報は外す（-map_metadata -1）
# - 早送りした区間と倍率は src/storyboards/b.ts の speedBadges と同じ値にする
#   （値を変えたら両方を直す）
#
# 使い方: cd video && bash scripts/cut_footage_b.sh
set -euo pipefail

cd "$(dirname "$0")/.."
SRC=public/private
OUT=public/footage
mkdir -p "$OUT"

ENC=(-an -map_metadata -1 -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r 30 -movflags +faststart)

# 手元の iPhone を撮った縦長の切り抜き（スマホの周りだけ。800×1080）
# F1（7 秒）: 3 択をタップ（4916 の 0.6〜5.2 秒）→ 自由記載を入力（4921 の全体）。どちらも 1.3 倍
ffmpeg -loglevel error -y -i "$SRC/IMG_4916.MOV" -i "$SRC/IMG_4921.MOV" -filter_complex "
[0:v]trim=0.6:5.2,setpts=(PTS-STARTPTS)/1.3,crop=800:1080:570:0[a];
[1:v]trim=0:4.63,setpts=(PTS-STARTPTS)/1.3,crop=800:1080:650:0[b];
[a][b]concat=n=2:v=1:a=0,trim=0:7,setpts=PTS-STARTPTS[v]" -map "[v]" "${ENC[@]}" "$OUT/F1.mp4"

# F2（5 秒）: つらくて書けない → 3 秒で記録 → 記録しました（4923 の 0.3〜6.2 秒を 1.18 倍）
ffmpeg -loglevel error -y -i "$SRC/IMG_4923.MOV" -filter_complex "
[0:v]trim=0.3:6.2,setpts=(PTS-STARTPTS)/1.18,crop=800:1080:650:0,trim=0:5,setpts=PTS-STARTPTS[v]" \
  -map "[v]" "${ENC[@]}" "$OUT/F2.mp4"

# F4（14 秒）: 受付番号を入れて送る → 医師画面の印刷待ちに A-023 → スマホのこれまでの記録（4929 の 0〜14 秒。等倍）
ffmpeg -loglevel error -y -i "$SRC/IMG_4929.MOV" -filter_complex "
[0:v]trim=0:14,setpts=PTS-STARTPTS[v]" -map "[v]" "${ENC[@]}" "$OUT/F4.mp4"

# F7（13 秒）: 変換ログ（4929 の 25〜44・59〜86・91〜105 秒の計 60 秒）を 8.5 秒に（約 7 倍）
# → 印刷待ち（106〜108 秒。等倍）→ A4 のレポート（110〜112.5 秒。等倍）
ffmpeg -loglevel error -y -i "$SRC/IMG_4929.MOV" -filter_complex "
[0:v]split=5[s1][s2][s3][s4][s5];
[s1]trim=25:44,setpts=PTS-STARTPTS[a];
[s2]trim=59:86,setpts=PTS-STARTPTS[b];
[s3]trim=91:105,setpts=PTS-STARTPTS[c];
[a][b][c]concat=n=3:v=1:a=0,setpts=PTS*8.5/60[log];
[s4]trim=106:108,setpts=PTS-STARTPTS[q];
[s5]trim=110:112.5,setpts=PTS-STARTPTS[r];
[log][q][r]concat=n=3:v=1:a=0,trim=0:13,setpts=PTS-STARTPTS[v]" -map "[v]" "${ENC[@]}" "$OUT/F7.mp4"

# F8（14 秒）: 文を入れて送る（4931 の 0〜3 秒。等倍）→ Claude の返事待ち（3〜43 秒を 1.5 秒に。約 27 倍）
# → 埋まったフォーム（43〜47.8 秒を 4 秒に。1.2 倍）→ 確認の画面（4932 の 1〜3.5 秒を 1.5 秒に）
# → 確かめた印・採用して登録・登録しました（4932 の 12.9〜16.9 秒。等倍）
ffmpeg -loglevel error -y -i "$SRC/IMG_4931.MOV" -i "$SRC/IMG_4932.MOV" -filter_complex "
[0:v]split=3[s1][s2][s3];
[s1]trim=0:3,setpts=PTS-STARTPTS[a];
[s2]trim=3:43,setpts=(PTS-STARTPTS)*1.5/40[b];
[s3]trim=43:47.8,setpts=(PTS-STARTPTS)*4/4.8[c];
[1:v]split=2[t1][t2];
[t1]trim=1:3.5,setpts=(PTS-STARTPTS)*1.5/2.5[d];
[t2]trim=12.9:16.9,setpts=PTS-STARTPTS[e];
[a][b][c][d][e]concat=n=5:v=1:a=0,trim=0:14,setpts=PTS-STARTPTS[v]" -map "[v]" "${ENC[@]}" "$OUT/F8.mp4"

for f in F1 F2 F4 F7 F8; do
  printf '%s ' "$f"
  ffprobe -v error -show_entries format=duration:stream=width,height,codec_type -of compact=p=0:nk=1 "$OUT/$f.mp4" | tr '\n' ' '
  echo
done

// 構成データから docs/video/narration-{a,b,c}.md と docs/video/shot-list.md を書き出す。
// TypeScript のデータを読むので `node --import tsx scripts/docs.mjs`（npm run docs）で動かす。
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DEVICE_LABEL, FOOTAGE, FOOTAGE_IDS } from "../src/footage.ts";
import { countChars } from "../src/lib/text.ts";
import { footageSegments, layoutScenes } from "../src/lib/timeline.ts";
import { STORYBOARDS } from "../src/storyboards/index.ts";

const FPS = 30;
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "..", "docs", "video");

const mmss = (sec) =>
  `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;

/** 表のセルに入れる（| と改行を逃がす） */
const cell = (text) =>
  String(text ?? "")
    .replace(/\|/g, "\\|")
    .replace(/\n/g, " ");

const sceneLabel = (scene) => {
  const segs = footageSegments(scene);
  if (segs.length === 0) return scene.kind;
  const parts = segs.map((g) => `${g.id} ${g.seconds}s`).join(" → ");
  return `${scene.kind}（${parts}）`;
};

const HEADER = (title) =>
  [
    `# ナレーション ${title}`,
    "",
    "生成物: `cd video && npm run docs` で `video/src/storyboards/` から書き出す。手で直さず構成データを直す。",
    "字幕の列が「（ナレーション）」の場面は、ナレーションをそのまま字幕にする（2 行以内・1 行 25 字前後に自動で区切る）。字数は空白を除いて数える。",
    "",
  ].join("\n");

const narrationDoc = (sb) => {
  const rows = layoutScenes(sb.scenes, FPS).map(
    ({ scene, from, durationInFrames }) => {
      const start = from / FPS;
      const end = (from + durationInFrames) / FPS;
      return `| ${mmss(start)}–${mmss(end)} | ${scene.seconds} | ${cell(sceneLabel(scene))} | ${cell(scene.screen)} | ${cell(scene.caption ?? "（ナレーション）")} | ${cell(scene.narration)} | ${countChars(scene.narration)} |`;
    },
  );
  const total = sb.scenes.reduce((sum, s) => sum + countChars(s.narration), 0);
  const seconds = sb.scenes.reduce((sum, s) => sum + s.seconds, 0);
  return [
    HEADER(sb.title),
    `合計 ${seconds} 秒・ナレーション ${total} 字（${(total / seconds).toFixed(1)} 字/秒）。Composition: \`${sb.compositionId}\`。`,
    "",
    "| 時刻 | 秒 | 場面 | 画面に出すもの | 字幕 | ナレーション | 字数 |",
    "|---|---|---|---|---|---|---|",
    ...rows,
    "",
    "## ナレーション全文（読み上げ用）",
    "",
    ...sb.scenes.map((s) => s.narration),
    "",
  ].join("\n");
};

const usageOf = (id) =>
  STORYBOARDS.flatMap((sb) =>
    sb.scenes.flatMap((scene, i) => {
      const seg = footageSegments(scene).find((g) => g.id === id);
      const bg = scene.props?.backgroundFootage === id;
      if (!seg && !bg) return [];
      const use = seg ? `${seg.seconds} 秒` : "背景（任意・ループ）";
      return [`${sb.compositionId} #${i + 1} ${scene.kind}（${use}）`];
    }),
  );

const shotListDoc = () => {
  const rows = FOOTAGE_IDS.map((id) => {
    const f = FOOTAGE[id];
    const uses = usageOf(id);
    return `| ${id} \`${f.slug}\` | ${cell(f.scene)} | ${DEVICE_LABEL[f.device]} | ${f.minSeconds} | ${cell(f.content)} | ${uses.length ? cell(uses.join("<br>")) : "（どの案でも使わない・任意）"} | \`video/public/footage/${id}.mp4\` |`;
  });
  return [
    "# 撮影リスト（3 案共通）",
    "",
    "生成物: `cd video && npm run docs` で `video/src/footage.ts` と構成データから書き出す。",
    "最低秒は 3 案で使う最長に合わせた値。長い分は動画側で切り詰める。音声は使わない（動画側で消す）。スマホは縦（9:16）、PC は横（16:9）。画面に実在の病院名・人名を入れない。",
    "置いた後に `npm run studio` などを動かすと、manifest（`src/footage.generated.ts`）が書き直されて枠のカードが録画に差し替わる。`F1_patient_today.mp4` のように id の後ろに `_` で名前を付けてもよい（.mov も可）。",
    "",
    "| id | 場面 | 端末 | 最低秒 | 撮る内容 | 使う場面 | 置き場所 |",
    "|---|---|---|---|---|---|---|",
    ...rows,
    "",
  ].join("\n");
};

mkdirSync(outDir, { recursive: true });
for (const sb of STORYBOARDS) {
  const file = join(outDir, `narration-${sb.variant}.md`);
  writeFileSync(file, narrationDoc(sb));
  console.log(`docs: ${file}`);
}
const shot = join(outDir, "shot-list.md");
writeFileSync(shot, shotListDoc());
console.log(`docs: ${shot}`);

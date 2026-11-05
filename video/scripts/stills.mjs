// 確認用の静止画: 各案の各場面の「後半 70% の時点」を1枚ずつ書き出す（out/stills/<案>-<番号>-<場面id>.png）。
// 一度だけ bundle して renderStill を回す。ブラウザを起動するので Claude Code のサンドボックス外で動かす。
// 使い方: npm run stills [-- DemoB]   （引数なしで 3 案すべて）
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import { layoutScenes } from "../src/lib/timeline.ts";
import { STORYBOARDS } from "../src/storyboards/index.ts";

const FPS = 30;
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "out", "stills");
mkdirSync(outDir, { recursive: true });

const wanted = process.argv.slice(2);
const boards =
  wanted.length === 0
    ? STORYBOARDS
    : STORYBOARDS.filter((b) => wanted.includes(b.compositionId));
if (boards.length === 0) {
  console.error(`案が見つからない: ${wanted.join(", ")}`);
  process.exit(1);
}

const serveUrl = await bundle({ entryPoint: join(root, "src", "index.ts") });
for (const board of boards) {
  const composition = await selectComposition({
    serveUrl,
    id: board.compositionId,
  });
  for (const t of layoutScenes(board.scenes, FPS)) {
    const frame = t.from + Math.floor(t.durationInFrames * 0.7);
    const no = String(t.index + 1).padStart(2, "0");
    const output = join(
      outDir,
      `${board.compositionId}-${no}-${t.scene.id}.png`,
    );
    await renderStill({
      composition,
      serveUrl,
      output,
      frame,
      imageFormat: "png",
    });
    console.log(`${output}（${(frame / FPS).toFixed(1)} 秒）`);
  }
}

// public/footage/*.mp4|mov と public/audio/*.mp3 を走査して src/footage.generated.ts を書く。
// 無いファイルを <OffthreadVideo> に渡すと描画が落ちるので、存在はここで判定する（onError に頼らない）。
import { readdirSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const footageDir = join(root, "public", "footage");
const audioDir = join(root, "public", "audio");
const outFile = join(root, "src", "footage.generated.ts");

const FOOTAGE_RE = /^(F\d{1,2})(?:[_-][^/]*)?\.(mp4|mov)$/i;
const AUDIO_RE = /^(narration-[abc])\.mp3$/i;
const KNOWN_IDS = new Set(Array.from({ length: 10 }, (_, i) => `F${i + 1}`));

const listDir = (dir) => {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((name) => !name.startsWith("."));
};

const collectFootage = () => {
  const found = {};
  for (const name of listDir(footageDir).sort()) {
    const m = FOOTAGE_RE.exec(name);
    if (!m) continue;
    const id = m[1].toUpperCase();
    if (!KNOWN_IDS.has(id)) continue;
    // 同じ id が複数あれば <id>.mp4 を優先し、無ければ名前順で最初のもの
    const exact = name.toLowerCase() === `${id.toLowerCase()}.mp4`;
    if (!found[id] || exact) found[id] = `footage/${name}`;
  }
  return found;
};

const collectAudio = () =>
  listDir(audioDir)
    .filter((name) => AUDIO_RE.test(name))
    .map((name) => name.replace(/\.mp3$/i, "").toLowerCase())
    .sort();

const render = (footage, audio) => {
  const ids = Object.keys(footage).sort(
    (a, b) => Number(a.slice(1)) - Number(b.slice(1)),
  );
  const footageBody =
    ids.length === 0
      ? "{}"
      : `{\n${ids.map((id) => `  ${id}: ${JSON.stringify(footage[id])},`).join("\n")}\n}`;
  const audioBody =
    audio.length === 0
      ? "[]"
      : `[${audio.map((a) => JSON.stringify(a)).join(", ")}]`;
  return [
    "// 生成物: scripts/footage-manifest.mjs が public/footage と public/audio を走査して書く。",
    "// 手で編集しない（npm run studio / render / still / bundle / test の前に自動で書き直される）。",
    'import type { FootageId } from "./types";',
    "",
    `export const footageFiles: Partial<Record<FootageId, string>> = ${footageBody};`,
    "",
    `export const audioFiles: string[] = ${audioBody};`,
    "",
  ].join("\n");
};

const footage = collectFootage();
const audio = collectAudio();
const next = render(footage, audio);
const prev = existsSync(outFile) ? readFileSync(outFile, "utf8") : "";
if (prev !== next) writeFileSync(outFile, next);
console.log(
  `footage-manifest: footage [${Object.keys(footage).join(", ") || "なし"}] / audio [${audio.join(", ") || "なし"}]`,
);

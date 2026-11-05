// public/footage/*.mp4|mov・public/screens/F<n>-<k>.png・public/audio/bgm.wav を走査して
// src/footage.generated.ts を書く。無いファイルを <OffthreadVideo> / <Img> に渡すと描画が落ちるので、
// 存在はここで判定する（onError に頼らない）。
import { readdirSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const footageDir = join(root, "public", "footage");
const screensDir = join(root, "public", "screens");
const outFile = join(root, "src", "footage.generated.ts");
// BGM は scripts/make_bgm.py が書く（案 B だけが使う）。無ければ BGM なしで成立する
const BGM_PATH = "audio/bgm.wav";

const FOOTAGE_RE = /^(F\d{1,2})(?:[_-][^/]*)?\.(mp4|mov)$/i;
const SCREEN_RE = /^(F\d{1,2})-(\d+)\.png$/i;
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

/** id ごとの静止画（k の数値順） */
const collectScreens = () => {
  const found = {};
  for (const name of listDir(screensDir)) {
    const m = SCREEN_RE.exec(name);
    if (!m) continue;
    const id = m[1].toUpperCase();
    if (!KNOWN_IDS.has(id)) continue;
    found[id] = [
      ...(found[id] ?? []),
      { k: Number(m[2]), path: `screens/${name}` },
    ];
  }
  return Object.fromEntries(
    Object.entries(found).map(([id, items]) => [
      id,
      [...items].sort((a, b) => a.k - b.k).map((x) => x.path),
    ]),
  );
};

const byIdNumber = (a, b) => Number(a.slice(1)) - Number(b.slice(1));

const renderScreens = (screens) => {
  const ids = Object.keys(screens).sort(byIdNumber);
  if (ids.length === 0) return "{}";
  const rows = ids.map(
    (id) =>
      `  ${id}: [${screens[id].map((p) => JSON.stringify(p)).join(", ")}],`,
  );
  return `{\n${rows.join("\n")}\n}`;
};

const collectBgm = () =>
  existsSync(join(root, "public", BGM_PATH)) ? BGM_PATH : null;

const render = (footage, screens, bgm) => {
  const ids = Object.keys(footage).sort(byIdNumber);
  const footageBody =
    ids.length === 0
      ? "{}"
      : `{\n${ids.map((id) => `  ${id}: ${JSON.stringify(footage[id])},`).join("\n")}\n}`;
  return [
    "// 生成物: scripts/footage-manifest.mjs が public/footage・public/screens・public/audio/bgm.wav を走査して書く。",
    "// 手で編集しない（npm run studio / render / still / bundle / test の前に自動で書き直される）。",
    'import type { FootageId } from "./types";',
    "",
    `export const footageFiles: Partial<Record<FootageId, string>> = ${footageBody};`,
    "",
    "/** 録画が無いときに出す静止画（public/screens/F<n>-<k>.png を k の順に） */",
    `export const screenFiles: Partial<Record<FootageId, string[]>> = ${renderScreens(screens)};`,
    "",
    "/** BGM（public/audio/bgm.wav。scripts/make_bgm.py が書く）。無ければ null */",
    `export const bgmFile: string | null = ${JSON.stringify(bgm)};`,
    "",
  ].join("\n");
};

const footage = collectFootage();
const screens = collectScreens();
const bgm = collectBgm();
const next = render(footage, screens, bgm);
const prev = existsSync(outFile) ? readFileSync(outFile, "utf8") : "";
if (prev !== next) writeFileSync(outFile, next);
const screenSummary = Object.entries(screens)
  .map(([id, list]) => `${id}×${list.length}`)
  .join(", ");
console.log(
  `footage-manifest: footage [${Object.keys(footage).join(", ") || "なし"}] / screens [${screenSummary || "なし"}] / bgm [${bgm ?? "なし"}]`,
);

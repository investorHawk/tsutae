// public/footage/*.mp4|mov・public/audio/*.mp3・public/screens/F<n>-<k>.png・public/voice/bgm.wav を走査して
// src/footage.generated.ts を書く。無いファイルを <OffthreadVideo> / <Img> に渡すと描画が落ちるので、
// 存在はここで判定する（onError に頼らない）。
// src/voice.generated.json（scripts/make_voice.py の出力）が無ければ [] で作る（import が落ちないように）。
import { readdirSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const footageDir = join(root, "public", "footage");
const audioDir = join(root, "public", "audio");
const screensDir = join(root, "public", "screens");
const outFile = join(root, "src", "footage.generated.ts");
const voiceFile = join(root, "src", "voice.generated.json");
// BGM は scripts/make_bgm.py が書く（DemoBVoice だけが使う）。無ければ BGM なしで成立する
const BGM_PATH = "voice/bgm.wav";

const FOOTAGE_RE = /^(F\d{1,2})(?:[_-][^/]*)?\.(mp4|mov)$/i;
const AUDIO_RE = /^(narration-[abc])\.mp3$/i;
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

const collectAudio = () =>
  listDir(audioDir)
    .filter((name) => AUDIO_RE.test(name))
    .map((name) => name.replace(/\.mp3$/i, "").toLowerCase())
    .sort();

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

const render = (footage, audio, screens, bgm) => {
  const ids = Object.keys(footage).sort(byIdNumber);
  const footageBody =
    ids.length === 0
      ? "{}"
      : `{\n${ids.map((id) => `  ${id}: ${JSON.stringify(footage[id])},`).join("\n")}\n}`;
  const audioBody =
    audio.length === 0
      ? "[]"
      : `[${audio.map((a) => JSON.stringify(a)).join(", ")}]`;
  return [
    "// 生成物: scripts/footage-manifest.mjs が public/footage・public/audio・public/screens・public/voice/bgm.wav を走査して書く。",
    "// 手で編集しない（npm run studio / render / still / bundle / test の前に自動で書き直される）。",
    'import type { FootageId } from "./types";',
    "",
    `export const footageFiles: Partial<Record<FootageId, string>> = ${footageBody};`,
    "",
    `export const audioFiles: string[] = ${audioBody};`,
    "",
    "/** 録画が無いときに出す静止画（public/screens/F<n>-<k>.png を k の順に） */",
    `export const screenFiles: Partial<Record<FootageId, string[]>> = ${renderScreens(screens)};`,
    "",
    "/** BGM（public/voice/bgm.wav。scripts/make_bgm.py が書く）。無ければ null */",
    `export const bgmFile: string | null = ${JSON.stringify(bgm)};`,
    "",
  ].join("\n");
};

const footage = collectFootage();
const audio = collectAudio();
const screens = collectScreens();
const bgm = collectBgm();
const next = render(footage, audio, screens, bgm);
const prev = existsSync(outFile) ? readFileSync(outFile, "utf8") : "";
if (prev !== next) writeFileSync(outFile, next);
// 声の一覧は make_voice.py が書く。無いときだけ空で作る（既にあれば触らない）
if (!existsSync(voiceFile)) writeFileSync(voiceFile, "[]\n");
const screenSummary = Object.entries(screens)
  .map(([id, list]) => `${id}×${list.length}`)
  .join(", ");
console.log(
  `footage-manifest: footage [${Object.keys(footage).join(", ") || "なし"}] / audio [${audio.join(", ") || "なし"}] / screens [${screenSummary || "なし"}] / bgm [${bgm ?? "なし"}]`,
);

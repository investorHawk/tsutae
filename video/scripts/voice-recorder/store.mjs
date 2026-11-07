// 録音の保存。声は public/voice/b<nn>.wav に置く（footage-manifest.mjs が見つける名前）。
// 前の録音は public の外へ退避し、録ったものは全て控えを残す。
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { normalizeScript } from "./script.mjs";

const VOICE_FILE_RE = /^(b\d{2})(?:[_-][^/]*)?\.(m4a|mp3|wav)$/i;
const TAKE_KINDS = new Set(["rehearsal", "record"]);
const MAX_SCRIPT_CHARS = 1000;

export const isVoiceKey = (key) => /^b(0[1-9]|1[0-2])$/.test(key);

const isWav = (bytes) => {
  const head = Buffer.from(bytes.subarray(0, 12)).toString("latin1");
  return head.startsWith("RIFF") && head.endsWith("WAVE");
};

const stamp = (date) =>
  date.toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);

const filesOf = (dir, key) =>
  readdirSync(dir).filter((name) => {
    const m = VOICE_FILE_RE.exec(name);
    return m !== null && m[1].toLowerCase() === key;
  });

/**
 * Range ヘッダーの解釈。全体を返すときは null、満たせないときは "invalid"、
 * それ以外は { start, end }（どちらも含む）。複数の範囲は全体で返してよいので扱わない
 */
export const parseRange = (header, size) => {
  const m = /^bytes=(\d*)-(\d*)$/.exec(header ?? "");
  if (!m || (m[1] === "" && m[2] === "")) return null;
  if (m[1] === "") {
    const length = Number(m[2]);
    if (length === 0 || size === 0) return "invalid";
    return { start: Math.max(0, size - length), end: size - 1 };
  }
  const start = Number(m[1]);
  const end = m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
  return start >= size || start > end ? "invalid" : { start, end };
};

/** WAV の秒数。読めなければ null */
export const wavSeconds = (buffer) => {
  if (!isWav(buffer)) return null;
  let at = 12;
  let byteRate = 0;
  while (at + 8 <= buffer.length) {
    const id = buffer.toString("latin1", at, at + 4);
    const size = buffer.readUInt32LE(at + 4);
    if (id === "fmt ") byteRate = buffer.readUInt32LE(at + 16);
    if (id === "data") return byteRate > 0 ? size / byteRate : null;
    at += 8 + size + (size % 2);
  }
  return null;
};

/** 保存済みの声（b01.wav を優先）。無ければ null */
export const savedVoice = (voiceDir, key) => {
  const files = filesOf(voiceDir, key);
  if (files.length === 0) return null;
  const file = files.includes(`${key}.wav`) ? `${key}.wav` : files[0];
  return { file, seconds: wavSeconds(readFileSync(join(voiceDir, file))) };
};

/** b<nn>.wav として保存する。同じ場面の前の録音は oldDir へ移す */
export const saveVoice = (voiceDir, oldDir, key, bytes, date = new Date()) => {
  if (!isVoiceKey(key)) throw new Error(`場面のキーが不正: ${key}`);
  if (!isWav(bytes)) throw new Error("WAV ではない");
  const tmp = join(voiceDir, `.${key}.tmp`);
  writeFileSync(tmp, bytes);
  const previous = filesOf(voiceDir, key);
  if (previous.length > 0) mkdirSync(oldDir, { recursive: true });
  for (const name of previous) {
    renameSync(join(voiceDir, name), join(oldDir, `${stamp(date)}-${name}`));
  }
  renameSync(tmp, join(voiceDir, `${key}.wav`));
  return `${key}.wav`;
};

/** 原稿の変更の一覧。{ b06: { original, edited, updatedAt } }。無ければ {} */
export const loadScriptEdits = (file) =>
  existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : {};

/** 変更後の原稿を保存する。元の文に戻したら、その場面の記録を消す */
export const saveScriptEdit = (
  file,
  key,
  original,
  text,
  date = new Date(),
) => {
  if (!isVoiceKey(key)) throw new Error(`場面のキーが不正: ${key}`);
  const edited = normalizeScript(text);
  if (edited === "") throw new Error("原稿が空です");
  if (Array.from(edited).length > MAX_SCRIPT_CHARS) {
    throw new Error("原稿が長すぎます");
  }
  const { [key]: _previous, ...others } = loadScriptEdits(file);
  const next =
    edited === original
      ? others
      : {
          ...others,
          [key]: { original, edited, updatedAt: date.toISOString() },
        };
  mkdirSync(dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, `${JSON.stringify(next, null, 2)}\n`);
  renameSync(tmp, file);
  return next;
};

/** 録った音の控え（リハーサルも本番も）。保存し損ねても後から拾える */
export const keepTake = (takesDir, key, kind, bytes, date = new Date()) => {
  if (!isVoiceKey(key)) throw new Error(`場面のキーが不正: ${key}`);
  if (!TAKE_KINDS.has(kind)) throw new Error(`種類が不正: ${kind}`);
  if (!isWav(bytes)) throw new Error("WAV ではない");
  mkdirSync(takesDir, { recursive: true });
  const name = `${stamp(date)}-${key}-${kind}.wav`;
  writeFileSync(join(takesDir, name), bytes);
  return name;
};

// 字幕: 字幕の文を「2 行以内・1 行 25 字前後」の塊に分け、塊の字数に比例して時間を配る。
import { countChars } from "./text";

export const LINE_TARGET = 25;
export const LINE_MAX = 28;
export const CHUNK_MAX = LINE_MAX * 2;

/** 行頭に置かない文字 */
const NO_LINE_START = "、。，．,.!?！？」』）)…ー";
/** 行末に置かない文字 */
const NO_LINE_END = "「『（(";

const chars = (s: string): string[] => Array.from(s);

const visibleLength = (s: string): number => countChars(s);

/** 句点・感嘆符・閉じ括弧の直後で文に分ける */
export const splitSentences = (text: string): string[] => {
  const out: string[] = [];
  let buf = "";
  const cs = chars(text);
  cs.forEach((c, i) => {
    buf += c;
    const next = cs[i + 1] ?? "";
    const endOfSentence = /[。！？]/.test(c) && !/[」』）]/.test(next);
    const closeAfterStop = /[」』]/.test(c) && /[。！？]/.test(cs[i - 1] ?? "");
    if (endOfSentence || closeAfterStop) {
      out.push(buf.trim());
      buf = "";
    }
  });
  if (buf.trim()) out.push(buf.trim());
  return out.filter((s) => s.length > 0);
};

/** 分けてよい位置（その位置の直前で切る）か */
const canBreakAt = (cs: string[], i: number): boolean =>
  i > 0 &&
  i < cs.length &&
  !NO_LINE_START.includes(cs[i]) &&
  !NO_LINE_END.includes(cs[i - 1]);

const HIRAGANA = /[\u3041-\u309F]/;
const PARTICLES = "はがをにでとものへ";

/** 空白を飛ばした、切れ目の直前・直後の文字 */
const neighbors = (cs: string[], i: number): [string, string] => {
  let p = i - 1;
  while (p >= 0 && cs[p] === " ") p -= 1;
  let n = i;
  while (n < cs.length && cs[n] === " ") n += 1;
  return [cs[p] ?? "", cs[n] ?? ""];
};

/**
 * 切る位置の良さ（大きいほど良い）。読点・句点の後を好み、
 * ひらがなの直前（送り仮名・助詞・「」の直後の助詞）は避ける。
 */
const breakScore = (cs: string[], i: number, target: number): number => {
  const [prev, next] = neighbors(cs, i);
  let bonus = 0;
  if ("、，,".includes(prev)) bonus = 12;
  else if ("。！？".includes(prev)) bonus = 14;
  else if (HIRAGANA.test(next)) bonus = -20;
  else if ("」』".includes(prev)) bonus = 10;
  else if ("「『".includes(next)) bonus = 8;
  else if (PARTICLES.includes(prev)) bonus = 4;
  else if (cs[i] === " " || cs[i - 1] === " ") bonus = 2;
  return bonus - Math.abs(i - target);
};

/** 文字列を 2 つに分ける位置を選ぶ（target は前半の目安の文字数） */
const bestBreak = (
  cs: string[],
  target: number,
  maxFirst: number,
  minFirst = 1,
): number => {
  let best = -1;
  let bestScore = -Infinity;
  for (let i = Math.max(1, minFirst); i < cs.length; i += 1) {
    if (i > maxFirst || !canBreakAt(cs, i)) continue;
    const score = breakScore(cs, i, target);
    if (score > bestScore) {
      bestScore = score;
      best = i;
    }
  }
  return best > 0 ? best : Math.min(target, cs.length - 1);
};

/** 長い文を CHUNK_MAX 以下の塊に分ける */
const splitLong = (sentence: string): string[] => {
  const cs = chars(sentence);
  if (visibleLength(sentence) <= CHUNK_MAX) return [sentence];
  const parts = Math.ceil(cs.length / CHUNK_MAX);
  const target = Math.ceil(cs.length / parts);
  const at = bestBreak(cs, target, CHUNK_MAX);
  const head = cs.slice(0, at).join("").trim();
  const tail = cs.slice(at).join("").trim();
  return [head, ...splitLong(tail)];
};

/** 短い文どうしを、CHUNK_MAX を超えない範囲でまとめる */
const mergeShort = (pieces: string[]): string[] =>
  pieces.reduce<string[]>((acc, p) => {
    const last = acc[acc.length - 1];
    if (last !== undefined && visibleLength(last + p) <= LINE_TARGET) {
      return [...acc.slice(0, -1), `${last}${p}`];
    }
    return [...acc, p];
  }, []);

/** 1 つの塊を 1〜2 行に折る */
export const wrapLines = (chunk: string): string[] => {
  const cs = chars(chunk);
  if (visibleLength(chunk) <= LINE_MAX) return [chunk];
  const limit = LINE_MAX + 2;
  const at = bestBreak(cs, Math.ceil(cs.length / 2), limit, cs.length - limit);
  return [cs.slice(0, at).join("").trim(), cs.slice(at).join("").trim()];
};

export interface SubtitleChunk {
  lines: string[];
  /** 場面の中での開始（0〜1） */
  start: number;
  /** 場面の中での終了（0〜1） */
  end: number;
}

/** 字幕の文を塊に分け、字数に比例して時間を配る */
export const buildSubtitleChunks = (text: string): SubtitleChunk[] => {
  const pieces = mergeShort(splitSentences(text).flatMap(splitLong));
  const total = pieces.reduce((sum, p) => sum + visibleLength(p), 0) || 1;
  let acc = 0;
  return pieces.map((p) => {
    const start = acc / total;
    acc += visibleLength(p);
    return { lines: wrapLines(p), start, end: acc / total };
  });
};

export interface ActiveChunk {
  index: number;
  /** その塊を出し始めるフレーム（場面の中で） */
  startFrame: number;
}

/** frame の時点で出す塊。塊の時間は場面全体に配り、場面の終わりより後は最後の塊を出し続ける */
export const chunkAt = (
  chunks: SubtitleChunk[],
  frame: number,
  durationInFrames: number,
): ActiveChunk => {
  const span = Math.max(1, durationInFrames);
  const progress = Math.min(1, Math.max(0, frame / span));
  const found = chunks.findIndex(
    (c) => progress >= c.start && progress < c.end,
  );
  const index = found >= 0 ? found : Math.max(0, chunks.length - 1);
  const startFrame = (chunks[index]?.start ?? 0) * span;
  return { index, startFrame };
};

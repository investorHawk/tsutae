/**
 * 未処理の記載（D6）で医師が選ぶ、伏せる区間の操作（純関数）。
 *
 * 位置は原文の code point の [start, end)（API の marks・spans と同じ単位）。ブラウザの
 * 選択（Selection）の位置は UTF-16 なので toCodePoint で直す。区間は位置順・重ならない
 * 形にそろえる（重なる・隣り合う区間は1つにまとめる。サーバーも重なりを断る）。
 * 引数は書き換えず、新しい配列を返す。
 */
import type { TextMark } from "../../api/types";

export type Span = TextMark;

export interface MaskPiece {
  text: string;
  start: number;
  end: number;
  masked: boolean;
}

/** 位置順に並べ、重なる・隣り合う区間をまとめる。空・逆順の区間は捨てる。 */
export function mergeSpans(spans: readonly Span[]): Span[] {
  const sorted = spans
    .filter((s) => s.end > s.start)
    .map((s) => ({ start: s.start, end: s.end }))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: Span[] = [];
  for (const span of sorted) {
    const last = merged[merged.length - 1];
    if (last && span.start <= last.end) {
      merged[merged.length - 1] = {
        start: last.start,
        end: Math.max(last.end, span.end),
      };
    } else {
      merged.push(span);
    }
  }
  return merged;
}

/** 区間を足す（伏せた区間と重なる・隣り合うなら1つにまとめる）。 */
export function addSpan(spans: readonly Span[], span: Span): Span[] {
  return mergeSpans([...spans, span]);
}

/** start から始まる区間を戻す（伏せ字をやめる）。 */
export function removeSpanAt(spans: readonly Span[], start: number): Span[] {
  return spans.filter((s) => s.start !== start).map((s) => ({ ...s }));
}

export function sameSpans(a: readonly Span[], b: readonly Span[]): boolean {
  return (
    a.length === b.length &&
    a.every((s, n) => s.start === b[n].start && s.end === b[n].end)
  );
}

/** text を伏せた区間とそうでない区間に分ける（spans は mergeSpans の形）。 */
export function splitByMasks(
  text: string,
  spans: readonly Span[],
): MaskPiece[] {
  const chars = Array.from(text);
  const pieces: MaskPiece[] = [];
  let cursor = 0;
  const push = (start: number, end: number, masked: boolean) => {
    if (end > start) {
      pieces.push({
        text: chars.slice(start, end).join(""),
        start,
        end,
        masked,
      });
    }
  };
  for (const { start, end } of spans) {
    if (start < cursor || end > chars.length) {
      continue;
    }
    push(cursor, start, false);
    push(start, end, true);
    cursor = end;
  }
  push(cursor, chars.length, false);
  return pieces;
}

/** text の UTF-16 の位置 offset を code point の位置に直す（範囲の外は端に寄せる）。 */
export function toCodePoint(text: string, offset: number): number {
  return Array.from(text.slice(0, Math.max(0, offset))).length;
}

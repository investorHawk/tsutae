import type { TextMark } from "../../api/types";

interface Piece {
  text: string;
  marked: boolean;
}

/**
 * text を marks（code point の [start, end)。位置順・重なりなし）で切り分ける。
 * 文字は code point で数える（絵文字などのサロゲートペアを割らない）。範囲の外・
 * 逆順の印は無視する（API の検査で弾くが、画面でも文を欠かさない）。
 */
export function splitMarks(text: string, marks: readonly TextMark[]): Piece[] {
  const chars = Array.from(text);
  const pieces: Piece[] = [];
  let cursor = 0;
  for (const { start, end } of marks) {
    if (start < cursor || end <= start || end > chars.length) {
      continue;
    }
    if (start > cursor) {
      pieces.push({ text: chars.slice(cursor, start).join(""), marked: false });
    }
    pieces.push({ text: chars.slice(start, end).join(""), marked: true });
    cursor = end;
  }
  if (cursor < chars.length) {
    pieces.push({ text: chars.slice(cursor).join(""), marked: false });
  }
  return pieces;
}

/**
 * 原文の疑われた語を <mark> で強調する（D6・D7-2。院内画面だけ）。印の無い部分は
 * 要素で包まず文字のまま置く（印が無ければ親の要素の文そのものになる）。
 */
export default function MarkedText({
  text,
  marks,
}: {
  text: string;
  marks: readonly TextMark[];
}) {
  return (
    <>
      {splitMarks(text, marks).map((piece, n) =>
        piece.marked ? (
          <mark key={n} className="d-suspect">
            {piece.text}
          </mark>
        ) : (
          piece.text
        ),
      )}
    </>
  );
}

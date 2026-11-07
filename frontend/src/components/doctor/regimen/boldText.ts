/**
 * Claude の返答の文の中の太字（**…**）だけを区切る純関数。HTML は作らず、描く側が
 * React の要素（<strong>）にする。対になっていない **・空の ****・中が * で始まる／
 * 終わるもの・改行をまたぐものは記号のまま残す。ほかの Markdown の記法は扱わない。
 */
export interface TextSegment {
  text: string;
  bold: boolean;
}

/** ** と ** の間（1文字以上・改行なし・最初と最後は * でない。いちばん近い ** で閉じる）。 */
const BOLD = /\*\*([^*\n](?:[^\n]*?[^*\n])??)\*\*/g;

export function boldSegments(text: string): TextSegment[] {
  const segments: TextSegment[] = [];
  let last = 0;
  for (const match of text.matchAll(BOLD)) {
    const start = match.index ?? 0;
    if (start > last) {
      segments.push({ text: text.slice(last, start), bold: false });
    }
    segments.push({ text: match[1], bold: true });
    last = start + match[0].length;
  }
  if (last < text.length) {
    segments.push({ text: text.slice(last), bold: false });
  }
  return segments;
}

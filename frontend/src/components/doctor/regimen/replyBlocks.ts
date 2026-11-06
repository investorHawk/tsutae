/**
 * Claude の返答の文を、行ごとに塊（段落・箇条書き／番号付き・表）へ分ける純関数。
 * HTML は作らず、描く側（ReplyText）が React の要素にする。見出し・コード・リンクなどの
 * ほかの記法は扱わず、段落の文のまま残す。形の崩れた表も元の文字のまま段落にする。
 */
import { markerOf, readList, type ListBlock } from "./replyList";
import { isTableLine, parseTable, type TableBlock } from "./replyTable";

export type { ListBlock, ListItem } from "./replyList";
export type { TableBlock } from "./replyTable";

export interface ParagraphBlock {
  kind: "paragraph";
  /** 段落の中の改行は保つ */
  text: string;
}

export type ReplyBlock = ParagraphBlock | ListBlock | TableBlock;

const isBlank = (line: string): boolean => line.trim() === "";

/** 段落の行（空行・項目の行・表の候補の行の手前まで）。 */
function readParagraph(lines: readonly string[], start: number): number {
  let i = start + 1;
  while (
    i < lines.length &&
    !isBlank(lines[i]) &&
    !markerOf(lines[i]) &&
    !isTableLine(lines[i])
  ) {
    i += 1;
  }
  return i;
}

/** lines[start] から塊を1つ読み、塊と次に読む行の位置を返す。 */
function readBlock(
  lines: readonly string[],
  start: number,
): [ReplyBlock, number] {
  if (isTableLine(lines[start])) {
    let end = start;
    while (end < lines.length && isTableLine(lines[end])) {
      end += 1;
    }
    const group = lines.slice(start, end);
    const table = parseTable(group);
    return [table ?? { kind: "paragraph", text: group.join("\n") }, end];
  }
  if (markerOf(lines[start])) {
    return readList(lines, start);
  }
  const end = readParagraph(lines, start);
  return [{ kind: "paragraph", text: lines.slice(start, end).join("\n") }, end];
}

export function replyBlocks(text: string): ReplyBlock[] {
  const lines = text.split(/\r?\n/);
  const blocks: ReplyBlock[] = [];
  let i = 0;
  let afterBlank = true;
  while (i < lines.length) {
    if (isBlank(lines[i])) {
      afterBlank = true;
      i += 1;
      continue;
    }
    const [block, next] = readBlock(lines, i);
    const prev = blocks[blocks.length - 1];
    if (
      !afterBlank &&
      prev?.kind === "paragraph" &&
      block.kind === "paragraph"
    ) {
      // 空行をはさまない段落（崩れた表の前後）は、改行でつなげて1つにする
      blocks[blocks.length - 1] = {
        kind: "paragraph",
        text: `${prev.text}\n${block.text}`,
      };
    } else {
      blocks.push(block);
    }
    afterBlank = false;
    i = next;
  }
  return blocks;
}

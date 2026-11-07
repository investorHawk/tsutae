/**
 * Claude の返答の箇条書き（- ）・番号付き（1. ）を、字下げの入れ子ごと読む純関数。
 * 字下げした続きの行は項目の文に足し、字下げの無い行・空行で並びを終える。
 */
export interface ListItem {
  text: string;
  children: ListBlock[];
}

export interface ListBlock {
  kind: "list";
  ordered: boolean;
  /** 番号付きの始まりの番号（箇条書きは 1） */
  start: number;
  items: ListItem[];
}

interface Marker {
  indent: number;
  ordered: boolean;
  start: number;
  text: string;
}

const MARKER = /^( *)(-|\d+\.) (.*)$/;

/** 項目の行なら字下げ・種類・文。そうでなければ null。 */
export function markerOf(line: string): Marker | null {
  const match = MARKER.exec(line);
  if (!match) {
    return null;
  }
  const [, spaces, mark, text] = match;
  const ordered = mark !== "-";
  return {
    indent: spaces.length,
    ordered,
    start: ordered ? parseInt(mark, 10) : 1,
    text: text.trim(),
  };
}

interface Frame {
  indent: number;
  list: ListBlock;
}

function listOf(marker: Marker): ListBlock {
  return {
    kind: "list",
    ordered: marker.ordered,
    start: marker.start,
    items: [],
  };
}

/**
 * 項目を置く並びを stack の上に用意する（深い字下げは直前の項目の子、同じ段で種類が
 * 変われば別の並び）。いちばん上の段で種類が変われば false（呼ぶ側が並びを終える）。
 */
function placeFor(stack: Frame[], marker: Marker): boolean {
  while (stack.length > 1 && marker.indent < stack[stack.length - 1].indent) {
    stack.pop();
  }
  const top = stack[stack.length - 1];
  const last = top.list.items[top.list.items.length - 1];
  if (marker.indent > top.indent && last) {
    const child = listOf(marker);
    last.children.push(child);
    stack.push({ indent: marker.indent, list: child });
    return true;
  }
  if (marker.ordered === top.list.ordered) {
    return true;
  }
  if (stack.length === 1) {
    return false;
  }
  const parent = stack[stack.length - 2].list.items;
  const sibling = listOf(marker);
  parent[parent.length - 1].children.push(sibling);
  stack[stack.length - 1] = { indent: top.indent, list: sibling };
  return true;
}

/** lines[start]（項目の行）から並びを読み、並びと次に読む行の位置を返す。 */
export function readList(
  lines: readonly string[],
  start: number,
): [ListBlock, number] {
  const first = markerOf(lines[start]);
  if (!first) {
    throw new Error("readList: 項目の行ではない");
  }
  const root = listOf(first);
  const stack: Frame[] = [{ indent: first.indent, list: root }];
  let item: ListItem | null = null;
  let i = start;
  for (; i < lines.length; i += 1) {
    const line = lines[i];
    const marker = markerOf(line);
    if (!marker) {
      if (!item || line.trim() === "" || !/^\s/.test(line)) {
        break;
      }
      item.text = `${item.text}\n${line.trim()}`;
      continue;
    }
    if (!placeFor(stack, marker)) {
      break;
    }
    item = { text: marker.text, children: [] };
    stack[stack.length - 1].list.items.push(item);
  }
  return [root, i];
}

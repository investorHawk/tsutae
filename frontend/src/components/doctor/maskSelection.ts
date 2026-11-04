/**
 * ブラウザの選択（Selection）を、原文の code point の区間に直す（D6 の「伏せ字にする」）。
 *
 * 伏せる所の表示（MaskEditor）は、原文を区間ごとの要素に分けて `data-start`・`data-end`
 * （code point）を持たせる。伏せていない区間は文字の span、伏せた区間は button。
 * - 選択の端が文字の中なら、その要素の data-start ＋（端までの UTF-16 を code point に直した数）
 * - 端が伏せた区間（button）の中なら、その区間ごと含める（選択と重なる区間はまとめる）
 * - 選択が空・表示の外にはみ出すなら null（何も伏せない）
 */
import { toCodePoint, type Span } from "./maskSpans";

type Range2 = [number, number];

function holderOf(container: Element, node: Node): HTMLElement | null {
  const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
  if (!(el instanceof HTMLElement)) {
    return null;
  }
  const holder = el.closest<HTMLElement>("[data-start]");
  return holder && container.contains(holder) ? holder : null;
}

function bounds(holder: HTMLElement): Range2 {
  return [Number(holder.dataset.start), Number(holder.dataset.end)];
}

/** 選択の端 (node, offset) の位置（範囲で返す。伏せた区間は区間ごと）。 */
function pointOf(
  container: HTMLElement,
  node: Node,
  offset: number,
  length: number,
): Range2 | null {
  if (node === container) {
    const child = container.childNodes[offset];
    const at =
      child instanceof HTMLElement ? Number(child.dataset.start) : length;
    return [at, at];
  }
  const holder = holderOf(container, node);
  if (holder === null) {
    return null;
  }
  const [start, end] = bounds(holder);
  if (holder.tagName === "BUTTON") {
    return [start, end];
  }
  if (node.nodeType === Node.TEXT_NODE) {
    const at = start + toCodePoint(node.textContent ?? "", offset);
    return [at, at];
  }
  const at = offset === 0 ? start : end;
  return [at, at];
}

/** 選択を区間にする。length は原文の code point の数。 */
export function selectionSpan(
  container: HTMLElement,
  selection: Selection | null,
  length: number,
): Span | null {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return null;
  }
  const range = selection.getRangeAt(0);
  const a = pointOf(container, range.startContainer, range.startOffset, length);
  const b = pointOf(container, range.endContainer, range.endOffset, length);
  if (a === null || b === null) {
    return null;
  }
  const start = Math.max(0, Math.min(a[0], b[0]));
  const end = Math.min(length, Math.max(a[1], b[1]));
  return end > start ? { start, end } : null;
}

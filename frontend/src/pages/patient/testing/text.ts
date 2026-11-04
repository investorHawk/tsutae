/**
 * 読み上げと見た目の文字（テスト用）。jsdom は CSS を当てず、textContent は
 * aria-hidden・visually-hidden の文字も含むので、ここで分けて集める。
 */

function collect(node: Node, skip: (el: Element) => boolean): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent ?? "";
  }
  if (node instanceof Element && skip(node)) {
    return "";
  }
  return Array.from(node.childNodes)
    .map((child) => collect(child, skip))
    .join("");
}

function squash(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** 読み上げる文字（aria-hidden の中は除く。visually-hidden は含む）。 */
export function spokenText(el: Element): string {
  return squash(
    collect(el, (child) => child.getAttribute("aria-hidden") === "true"),
  );
}

/** 画面に見える文字（visually-hidden の中は除く。aria-hidden は含む）。 */
export function visibleText(el: Element): string {
  return squash(
    collect(el, (child) => child.classList.contains("visually-hidden")),
  );
}

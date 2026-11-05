/**
 * タブの並び（role=tablist）のキーボード操作: ←→ で隣のタブ、Home・End で端のタブへ
 * focus を移す（WAI-ARIA のタブ）。選ぶのは Enter・Space（タブを開くと下書きを作る画面が
 * あるので、focus を移しただけでは開かない）。
 */
import type { KeyboardEvent } from "react";

/** 押したキーで移る先の添え字（移らないキーなら null）。端では反対の端へ回る。 */
export function nextTabIndex(
  key: string,
  index: number,
  count: number,
): number | null {
  if (count <= 0) {
    return null;
  }
  switch (key) {
    case "ArrowRight":
      return (index + 1) % count;
    case "ArrowLeft":
      return (index - 1 + count) % count;
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return null;
  }
}

/** tablist の onKeyDown。押せるタブ（disabled でない）の間で focus を移す。 */
export function moveTabFocus(event: KeyboardEvent<HTMLElement>): void {
  const tabs = [
    ...event.currentTarget.querySelectorAll<HTMLElement>(
      '[role="tab"]:not([disabled])',
    ),
  ];
  const index = tabs.indexOf(document.activeElement as HTMLElement);
  if (index < 0) {
    return;
  }
  const next = nextTabIndex(event.key, index, tabs.length);
  if (next === null) {
    return;
  }
  event.preventDefault();
  tabs[next]?.focus();
}

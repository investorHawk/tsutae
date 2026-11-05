import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

/** チャットの枠の sticky の top（px）。CSS は --rf-chat-top で受ける（値はここだけに持つ）。 */
export const CHAT_STICKY_TOP = 40;
/** 枠の下と画面の下端の余白（px）。 */
const CHAT_BOTTOM_GAP = 24;

/**
 * 枠の上端から画面の下端までの高さ。スクロールの前は枠が見出しの下にあるので、その分を引く。
 * 枠が画面より下にあれば 0（負の高さは CSS で無効になる。下限は CSS の min-height）。
 */
export function chatHeightOf(top: number, viewportHeight: number): number {
  const start = Math.max(top, CHAT_STICKY_TOP);
  return Math.max(0, viewportHeight - start - CHAT_BOTTOM_GAP);
}

function applyFit(el: HTMLElement | null): void {
  if (!el) {
    return;
  }
  const height = chatHeightOf(
    el.getBoundingClientRect().top,
    window.innerHeight,
  );
  el.style.setProperty("--rf-chat-top", `${CHAT_STICKY_TOP}px`);
  el.style.setProperty("--rf-chat-h", `${height}px`);
}

/**
 * 枠の高さを画面に合わせる（入力欄がスクロールなしで見える）。返す ref を枠に付ける。
 * scroll で描き直さないよう、値は state にせず枠の CSS 変数に直接入れる。
 *
 * 描くたびに測るのは、下書きの変更のほか、枠の上に帯が出たとき（scroll も resize も来ない）と、
 * 「レポートの形式」のタブから戻ったとき（隠れている間は測れない）にも合わせるため。
 * scroll と resize は1回の描画の枠につき1回に間引く。
 */
export function useChatFit(): RefObject<HTMLElement> {
  const ref = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    applyFit(ref.current);
  });

  useEffect(() => {
    let frame: number | null = null;
    const schedule = () => {
      if (frame !== null) {
        return;
      }
      frame = window.requestAnimationFrame(() => {
        frame = null;
        applyFit(ref.current);
      });
    };
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, { passive: true });
    return () => {
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule);
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
      }
    };
  }, []);

  return ref;
}

// 時計の表示（m:ss）と、before / after の時計の秒。React / remotion を import しない。
import type { SceneProps } from "../types";

export const formatClock = (seconds: number): string => {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** clockSeconds が無いときの秒（案 A・C の 3 分 → 30 秒） */
export const DEFAULT_CLOCK_SECONDS = { before: 180, after: 30 } as const;

/** before: 時計が回り切る秒。after: 時計に出す秒 */
export const clockSecondsOf = (
  kind: keyof typeof DEFAULT_CLOCK_SECONDS,
  props: Pick<SceneProps, "clockSeconds"> | undefined,
): number => props?.clockSeconds ?? DEFAULT_CLOCK_SECONDS[kind];

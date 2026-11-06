// closing の時間の棒グラフの計算（棒の長さの割合と、伸びる時刻）。React / remotion を import しない。
import type { CompareItem } from "../types";

/** 最長の行を 1 にした、各行の棒の長さの割合（0〜1）。負の秒は 0 とする */
export const barRatios = (items: readonly CompareItem[]): number[] => {
  const max = Math.max(0, ...items.map((it) => it.seconds));
  return items.map((it) => (max > 0 ? Math.max(0, it.seconds) / max : 0));
};

/** 棒を出し始めるフレーム・1 本が伸びるフレーム・棒どうしの間 */
const FIRST_BAR_AT = 14;
const BAR_FRAMES = 30;
const BAR_GAP = 8;
const FACTS_DELAY = 8;

export interface CompareSchedule {
  /** 各行の棒が伸び始めるフレーム（場面の中で） */
  barStarts: number[];
  /** 1 本の棒が伸び切るまでのフレーム */
  barFrames: number;
  /** 事実を出すフレーム */
  factsAt: number;
}

/** 棒は 1 行目から順に、前の棒が伸び切ってから伸びる。事実は最後の棒の後 */
export const compareSchedule = (count: number): CompareSchedule => {
  const barStarts = Array.from(
    { length: Math.max(0, count) },
    (_, i) => FIRST_BAR_AT + i * (BAR_FRAMES + BAR_GAP),
  );
  const lastEnd =
    barStarts.length > 0
      ? barStarts[barStarts.length - 1] + BAR_FRAMES
      : FIRST_BAR_AT;
  return { barStarts, barFrames: BAR_FRAMES, factsAt: lastEnd + FACTS_DELAY };
};

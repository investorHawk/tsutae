// closing の数字の文字列（t は 0〜1 のカウントの進み）。React / remotion を import しない。
import type { Stat } from "../types";
import { formatClock } from "./clock";

export const statText = (stat: Stat, t: number): string => {
  const from = stat.from ?? 0;
  const value = from + (stat.to - from) * t;
  if (stat.format === "clock") return formatClock(value);
  return `${Math.round(value).toLocaleString("ja-JP")}${stat.unit ?? ""}`;
};

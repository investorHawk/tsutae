// sample-report.png（1000×1300）の中の領域。画像を目で見て決めた座標（px）。
// 描画での位置は Studio で要確認（サンドボックス内では描画を確かめていない）。
import type { ReportFocus } from "../types";

export const REPORT_IMAGE = "images/sample-report.png";
export const REPORT_SIZE = { width: 1000, height: 1300 } as const;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const REGIONS: Record<ReportFocus, Rect> = {
  alerts: { x: 132, y: 145, w: 736, h: 100 },
  timeline: { x: 132, y: 252, w: 736, h: 340 },
  symptoms: { x: 132, y: 598, w: 736, h: 154 },
  quotes: { x: 132, y: 752, w: 736, h: 220 },
};

export const REGION_LABEL: Record<ReportFocus, string> = {
  alerts: "要確認",
  timeline: "経過表（Day 別）",
  symptoms: "症状別の時系列",
  quotes: "引用（原文・伏せ字後）",
};

/** 要確認の行（食い違い・発熱・つらくて書けない） */
export const ALERT_ROWS: Rect[] = [
  { x: 138, y: 172, w: 724, h: 19 },
  { x: 138, y: 190, w: 724, h: 19 },
  { x: 138, y: 208, w: 724, h: 19 },
];

/** 領域ごとに枠を付ける所 */
export const HIGHLIGHTS: Record<ReportFocus, Rect[]> = {
  alerts: ALERT_ROWS,
  // Day5 の列（代・回の印がある日）
  timeline: [{ x: 405, y: 276, w: 47, h: 264 }],
  // 症状別の時系列の「口内炎 Day5〜（10/31）『おとといの夜から口内炎がいたい』」
  symptoms: [{ x: 140, y: 709, w: 722, h: 20 }],
  // 引用の「Day7 11/2 おとといの夜から口内炎がいたい。おかゆにした」
  quotes: [{ x: 140, y: 871, w: 722, h: 20 }],
};

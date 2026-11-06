import { describe, expect, it } from "vitest";
import { barRatios, compareSchedule } from "../src/lib/compare";

describe("barRatios（棒の長さの割合）", () => {
  it("最長の行を 1 にして、秒に比例させる（2:00 と 0:20 は 6 分の 1）", () => {
    const ratios = barRatios([
      { label: "これまで", seconds: 120 },
      { label: "つたえ", seconds: 20 },
    ]);
    expect(ratios[0]).toBe(1);
    expect(ratios[1]).toBeCloseTo(1 / 6);
  });

  it("最長が先頭でなくてもよい", () => {
    expect(
      barRatios([
        { label: "a", seconds: 30 },
        { label: "b", seconds: 60 },
      ]),
    ).toEqual([0.5, 1]);
  });

  it("全て 0 秒・負の秒・空でも NaN にしない", () => {
    expect(barRatios([{ label: "a", seconds: 0 }])).toEqual([0]);
    expect(
      barRatios([
        { label: "a", seconds: -5 },
        { label: "b", seconds: 10 },
      ]),
    ).toEqual([0, 1]);
    expect(barRatios([])).toEqual([]);
  });

  it("引数を書き換えない", () => {
    const items = [
      { label: "a", seconds: 120 },
      { label: "b", seconds: 20 },
    ];
    const before = JSON.stringify(items);
    barRatios(items);
    expect(JSON.stringify(items)).toBe(before);
  });
});

describe("compareSchedule（棒が伸びる順と事実を出す時刻）", () => {
  it("棒は 1 行目から順に、前の棒が伸び切ってから伸びる。事実はその後", () => {
    const { barStarts, barFrames, factsAt } = compareSchedule(2);
    expect(barStarts).toHaveLength(2);
    expect(barStarts[1]).toBeGreaterThanOrEqual(barStarts[0] + barFrames);
    expect(factsAt).toBeGreaterThanOrEqual(barStarts[1] + barFrames);
  });

  it("案 B の締め（20 秒・最後のカードへは 38%）の切り替えより前に事実が出て 2 秒以上残る", () => {
    const endAt = Math.round(20 * 30 * 0.38);
    expect(compareSchedule(2).factsAt + 60).toBeLessThanOrEqual(endAt);
  });
});

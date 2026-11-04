import { describe, expect, it } from "vitest";
import { slideStates } from "../src/lib/slides";

describe("静止画のスライド（区間を枚数で均等に割る）", () => {
  it("1 枚なら最初から最後まで出し、ゆっくり 1.0 → 1.04 に寄る", () => {
    const first = slideStates(1, 90, 0)[0];
    const last = slideStates(1, 90, 89)[0];
    expect(first).toMatchObject({ visible: true, opacity: 1, scale: 1 });
    expect(last.visible).toBe(true);
    expect(last.scale).toBeGreaterThan(1.03);
    expect(last.scale).toBeLessThanOrEqual(1.04);
  });

  it("3 枚を 90 フレームで 30 フレームずつ切り替える", () => {
    const at = (frame: number) => slideStates(3, 90, frame);
    expect(at(10).map((s) => s.visible)).toEqual([true, false, false]);
    expect(at(60 + 8).map((s) => s.visible)).toEqual([false, false, true]);
    expect(at(60 + 8)[2].opacity).toBe(1);
  });

  it("切り替えは 8 フレームのクロスフェード（新しい画像が上に重なる）", () => {
    const mid = slideStates(2, 60, 34);
    expect(mid[0]).toMatchObject({ visible: true, opacity: 1 });
    expect(mid[1].visible).toBe(true);
    expect(mid[1].opacity).toBeCloseTo(0.5, 6);
    expect(slideStates(2, 60, 30)[1].opacity).toBe(0);
    expect(slideStates(2, 60, 38)[1].opacity).toBe(1);
  });

  it("0 枚なら空", () => {
    expect(slideStates(0, 60, 0)).toEqual([]);
  });
});

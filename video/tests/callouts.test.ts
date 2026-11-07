import { describe, expect, it } from "vitest";
import { calloutAt } from "../src/lib/callouts";

describe("録画の場面の札（callouts）", () => {
  it("区間と札が同じ数なら、区間ごとに 1 つ（案 A・C と案 B の b05 の形）", () => {
    const callouts = ["一", "二", "三"];
    expect(calloutAt(callouts, 0, 3, 0.9)).toBe("一");
    expect(calloutAt(callouts, 1, 3, 0)).toBe("二");
    expect(calloutAt(callouts, 2, 3, 0.99)).toBe("三");
  });

  it("null の札と、札の足りない区間は出さない", () => {
    expect(calloutAt([null, "二"], 0, 2, 0.5)).toBeNull();
    expect(calloutAt(["一"], 1, 2, 0.5)).toBeNull();
    expect(calloutAt([], 0, 1, 0.5)).toBeNull();
  });

  it("区間より札が多ければ、最後の区間を札の数で均等に割って順に出す（b06）", () => {
    const callouts = ["前半", "後半"];
    expect(calloutAt(callouts, 0, 1, 0)).toBe("前半");
    expect(calloutAt(callouts, 0, 1, 0.49)).toBe("前半");
    expect(calloutAt(callouts, 0, 1, 0.5)).toBe("後半");
    expect(calloutAt(callouts, 0, 1, 1)).toBe("後半");
  });

  it("途中の区間は自分の札だけを出す", () => {
    expect(calloutAt(["一", "二", "三"], 0, 2, 0.9)).toBe("一");
    expect(calloutAt(["一", "二", "三"], 1, 2, 0.9)).toBe("三");
  });

  it("引数の配列を変えない", () => {
    const callouts = Object.freeze(["前半", "後半"]) as readonly string[];
    expect(calloutAt(callouts, 0, 1, 0.7)).toBe("後半");
    expect(callouts).toEqual(["前半", "後半"]);
  });
});

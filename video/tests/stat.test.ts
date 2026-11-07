import { describe, expect, it } from "vitest";
import { statText } from "../src/lib/stat";
import type { Stat } from "../src/types";

describe("statText（closing の数字）", () => {
  it("clock は from から to まで m:ss で数える", () => {
    const stat: Stat = {
      label: "聞き取り",
      format: "clock",
      from: 180,
      to: 30,
    };
    expect(statText(stat, 0)).toBe("3:00");
    expect(statText(stat, 1)).toBe("0:30");
  });

  it("number は整数に丸め、桁区切りをつける", () => {
    const stat: Stat = {
      label: "テスト",
      format: "number",
      to: 7163,
      unit: "件",
    };
    expect(statText(stat, 1)).toBe("7,163件");
    expect(statText(stat, 0)).toBe("0件");
    expect(statText({ ...stat, to: 93, unit: "%" }, 0.5)).toBe("47%");
  });
});

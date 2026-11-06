import { describe, expect, it } from "vitest";
import {
  clockSecondsOf,
  DEFAULT_CLOCK_SECONDS,
  formatClock,
} from "../src/lib/clock";

describe("formatClock", () => {
  it("秒を m:ss で出す", () => {
    expect(formatClock(120)).toBe("2:00");
    expect(formatClock(20)).toBe("0:20");
    expect(formatClock(-3)).toBe("0:00");
  });
});

describe("clockSecondsOf（before / after の時計の秒）", () => {
  it("clockSeconds が無ければ before は 180 秒、after は 30 秒（案 A・C）", () => {
    expect(DEFAULT_CLOCK_SECONDS).toEqual({ before: 180, after: 30 });
    expect(clockSecondsOf("before", undefined)).toBe(180);
    expect(clockSecondsOf("after", {})).toBe(30);
  });

  it("clockSeconds があればその秒（案 B は 120 と 20）", () => {
    expect(clockSecondsOf("before", { clockSeconds: 120 })).toBe(120);
    expect(clockSecondsOf("after", { clockSeconds: 20 })).toBe(20);
  });
});

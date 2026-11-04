import { describe, expect, it } from "vitest";
import { formatDateTime, formatElapsed, formatTime } from "./format";

describe("formatDateTime", () => {
  it("JST の 月/日 時:分 にする", () => {
    expect(formatDateTime("2026-11-09T10:23:05+09:00")).toBe("11/09 10:23");
  });

  it("UTC の時刻も JST に直す", () => {
    expect(formatDateTime("2026-11-09T01:03:05Z")).toBe("11/09 10:03");
  });

  it("読めない値はそのまま返す", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});

describe("formatTime", () => {
  it("JST の 時:分:秒 にする", () => {
    expect(formatTime("2026-11-09T10:23:05+09:00")).toBe("10:23:05");
  });

  it("読めない値はそのまま返す", () => {
    expect(formatTime("")).toBe("");
  });
});

describe("formatElapsed", () => {
  it("1分未満は秒（小数1桁）", () => {
    expect(formatElapsed(0)).toBe("+0.0秒");
    expect(formatElapsed(1234)).toBe("+1.2秒");
  });

  it("1分以上は 分・秒", () => {
    expect(formatElapsed(65_000)).toBe("+1分05秒");
  });

  it("負の値や数でない値は空文字", () => {
    expect(formatElapsed(-1)).toBe("");
    expect(formatElapsed(Number.NaN)).toBe("");
  });
});

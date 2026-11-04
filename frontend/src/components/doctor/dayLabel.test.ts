import { describe, expect, it } from "vitest";
import { formatClock, formatDay } from "./dayLabel";

// 2026-11-04 12:00 JST（今年は 2026）
const NOW = new Date("2026-11-04T03:00:00Z");

describe("formatDay（日付）", () => {
  it("今年の日付は「11月9日（月）」（ゼロ埋めしない）", () => {
    expect(formatDay("2026-11-09", NOW)).toBe("11月9日（月）");
    expect(formatDay("2026-01-04", NOW)).toBe("1月4日（日）");
  });

  it("曜日は暦どおり（日〜土）", () => {
    const days = [
      "2026-11-08",
      "2026-11-09",
      "2026-11-10",
      "2026-11-11",
      "2026-11-12",
      "2026-11-13",
      "2026-11-14",
    ].map((d) => formatDay(d, NOW).slice(-2, -1));
    expect(days).toEqual(["日", "月", "火", "水", "木", "金", "土"]);
  });

  it("年が今年と違う時だけ年を付ける", () => {
    expect(formatDay("2025-11-09", NOW)).toBe("2025年11月9日（日）");
    expect(formatDay("2027-01-01", NOW)).toBe("2027年1月1日（金）");
  });

  it("今年は東京の日付で決める（UTC では前の年の大晦日でも）", () => {
    const newYearTokyo = new Date("2026-12-31T16:00:00Z"); // 2027-01-01 01:00 JST
    expect(formatDay("2027-01-01", newYearTokyo)).toBe("1月1日（金）");
  });

  it("読めない値・暦に無い日はそのまま返す", () => {
    expect(formatDay("not-a-date", NOW)).toBe("not-a-date");
    expect(formatDay("2026-02-30", NOW)).toBe("2026-02-30");
  });
});

describe("formatDay（日時）", () => {
  it("+09:00 の日時は「11月9日（月）18:16」", () => {
    expect(formatDay("2026-11-09T18:16:42+09:00", NOW)).toBe(
      "11月9日（月）18:16",
    );
  });

  it("UTC の日時も東京の日付と時刻に直す（日付が変わる）", () => {
    expect(formatDay("2026-11-08T15:05:00Z", NOW)).toBe("11月9日（月）00:05");
  });

  it("年が今年と違えば年を付ける", () => {
    expect(formatDay("2025-11-09T09:00:00+09:00", NOW)).toBe(
      "2025年11月9日（日）09:00",
    );
  });

  it("読めない値はそのまま返す", () => {
    expect(formatDay("2026-11-09T99:00:00+09:00", NOW)).toBe(
      "2026-11-09T99:00:00+09:00",
    );
  });
});

describe("formatClock", () => {
  it("東京の「18:16」", () => {
    expect(formatClock("2026-11-09T18:16:42+09:00")).toBe("18:16");
    expect(formatClock("2026-11-09T00:05:00Z")).toBe("09:05");
  });

  it("読めない値は空文字", () => {
    expect(formatClock("")).toBe("");
  });
});

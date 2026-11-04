import { describe, expect, it } from "vitest";
import { ENTRIES } from "../../pages/patient/testing/fixtures";
import { formatRecordedAt, newestFirst } from "./history";

describe("newestFirst", () => {
  it("記録日時の新しい順に並べた新しい配列を返す", () => {
    const original = [...ENTRIES];
    const sorted = newestFirst(original);
    expect(sorted.map((e) => e.id)).toEqual([13, 12, 11]);
    expect(original.map((e) => e.id)).toEqual([11, 12, 13]);
  });

  it("同じ日時なら id の大きい方が先", () => {
    const a = { ...ENTRIES[0]!, id: 1 };
    const b = { ...ENTRIES[0]!, id: 2 };
    expect(newestFirst([a, b]).map((e) => e.id)).toEqual([2, 1]);
  });

  it("時差の違う書き方でも文字列ではなく時刻で比べる", () => {
    // 11/02 00:30 (+09:00) = 11/01 15:30Z なので、11/01 16:00Z の方が新しい
    const a = {
      ...ENTRIES[0]!,
      id: 1,
      recorded_at: "2026-11-02T00:30:00+09:00",
    };
    const b = { ...ENTRIES[0]!, id: 2, recorded_at: "2026-11-01T16:00:00Z" };
    expect(newestFirst([a, b]).map((e) => e.id)).toEqual([2, 1]);
  });
});

describe("formatRecordedAt", () => {
  it("記録日と時刻（時:分）を数字だけで出す", () => {
    expect(formatRecordedAt(ENTRIES[1]!)).toBe("2026-10-31 19:30");
  });

  it("時刻が読めなければ記録日だけ", () => {
    expect(formatRecordedAt({ ...ENTRIES[1]!, recorded_at: "broken" })).toBe(
      "2026-10-31",
    );
  });
});

import { describe, expect, it } from "vitest";
import { ENTRIES, s } from "../../pages/patient/testing/fixtures";
import {
  formatDate,
  formatRecordedAt,
  newestFirst,
  recordedAtParts,
} from "./history";

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

describe("recordedAtParts", () => {
  it("記録日（JST）の月・日・曜日（0=日曜）と、記録した時の表記の時:分", () => {
    // 2026-10-31 は土曜
    expect(recordedAtParts(ENTRIES[1]!)).toEqual({
      month: 10,
      day: 31,
      weekday: 6,
      time: "19:30",
    });
  });

  it("時の先頭の 0 は付けない", () => {
    // 2026-11-02 は月曜
    expect(recordedAtParts(ENTRIES[2]!)).toEqual({
      month: 11,
      day: 2,
      weekday: 1,
      time: "8:10",
    });
  });

  it("曜日は端末の時差によらず記録日で決まる", () => {
    const entry = {
      ...ENTRIES[0]!,
      record_date: "2026-11-09",
      recorded_at: "2026-11-09T00:05:00+09:00",
    };
    expect(recordedAtParts(entry)).toMatchObject({ weekday: 1, time: "0:05" });
  });

  it("時刻が読めなければ time は null", () => {
    expect(
      recordedAtParts({ ...ENTRIES[1]!, recorded_at: "broken" })?.time,
    ).toBeNull();
  });

  it.each(["broken", "2026-13-01", "2026-02-30", ""])(
    "記録日が読めなければ null（%s）",
    (bad) => {
      expect(recordedAtParts({ ...ENTRIES[1]!, record_date: bad })).toBeNull();
    },
  );

  it("引数を書き換えない", () => {
    const entry = Object.freeze({ ...ENTRIES[1]! });
    expect(() => recordedAtParts(entry)).not.toThrow();
  });
});

describe("formatRecordedAt", () => {
  it("定型文の history.date と weekday.* で「月日（曜）時:分」にする", () => {
    const date = s("history.date")
      .replace("{month}", "11")
      .replace("{day}", "9")
      .replace("{weekday}", s("weekday.1"));
    const entry = {
      ...ENTRIES[1]!,
      record_date: "2026-11-09",
      recorded_at: "2026-11-09T13:47:00+09:00",
    };
    expect(formatRecordedAt(entry, s)).toBe(`${date}13:47`);
  });

  it("時刻が読めなければ日付だけ", () => {
    const date = s("history.date")
      .replace("{month}", "10")
      .replace("{day}", "31")
      .replace("{weekday}", s("weekday.6"));
    expect(formatRecordedAt({ ...ENTRIES[1]!, recorded_at: "broken" }, s)).toBe(
      date,
    );
  });

  it("記録日が読めなければ記録日の文字をそのまま出す", () => {
    expect(formatRecordedAt({ ...ENTRIES[1]!, record_date: "broken" }, s)).toBe(
      "broken",
    );
  });
});

describe("formatDate（今日の記録の見出しの日付）", () => {
  const t = (key: string) => s(key);

  it("YYYY-MM-DD を定型文の history.date と weekday.* で「月日（曜）」にする", () => {
    // 2026-11-09 は月曜
    expect(formatDate("2026-11-09", t)).toBe(
      s("history.date")
        .replace("{month}", "11")
        .replace("{day}", "9")
        .replace("{weekday}", s("weekday.1")),
    );
  });

  it.each(["", "2026-02-30", "2026-13-01", "2026-11-09T10:00:00+09:00"])(
    "読めない日付（%s）は null",
    (value) => {
      expect(formatDate(value, t)).toBeNull();
    },
  );
});

import { describe, expect, it } from "vitest";
import {
  emptyValueOf,
  formatDays,
  formatList,
  parseDays,
  parseList,
  parseWholeNumber,
  valueText,
} from "./fieldValues";

describe("valueText（値を1行の文字に）", () => {
  it.each<[unknown, string]>([
    ["大腸がん", "大腸がん"],
    [14, "14"],
    [["下痢", "軟便"], "下痢、軟便"],
    [
      [
        { start: 1, end: 3 },
        { start: 8, end: 8 },
      ],
      "Day1〜3・8",
    ],
    [null, "（空）"],
    ["", "（空）"],
  ])("%j → %s", (value, text) => {
    expect(valueText(value)).toBe(text);
  });
});

describe("parseDays（Day の範囲の入力 → DayRange[]）", () => {
  it.each([
    ["Day1", [{ start: 1, end: 1 }]],
    [
      "Day1・8・15",
      [
        { start: 1, end: 1 },
        { start: 8, end: 8 },
        { start: 15, end: 15 },
      ],
    ],
    [
      "Day1〜5・8〜12",
      [
        { start: 1, end: 5 },
        { start: 8, end: 12 },
      ],
    ],
    ["1-3", [{ start: 1, end: 3 }]],
    ["day 1~14", [{ start: 1, end: 14 }]],
    [
      "Ｄａｙ１〜３、８",
      [
        { start: 1, end: 3 },
        { start: 8, end: 8 },
      ],
    ],
    [
      "Day1, Day15",
      [
        { start: 1, end: 1 },
        { start: 15, end: 15 },
      ],
    ],
  ])("%s", (text, ranges) => {
    expect(parseDays(text)).toEqual({ ok: true, value: ranges });
  });

  it("空は空の一覧（欄を空にする）", () => {
    expect(parseDays("  ")).toEqual({ ok: true, value: [] });
  });

  it.each(["Day", "あさ", "Day1〜", "Day0", "Day5〜3", "1.5"])(
    "読めない形は理由つきで返す（%s）",
    (text) => {
      const result = parseDays(text);
      expect(result.ok).toBe(false);
    },
  );
});

describe("formatDays", () => {
  it("1日は DayN、範囲は N〜M、複数は「・」でつなぐ", () => {
    expect(formatDays([{ start: 1, end: 1 }])).toBe("Day1");
    expect(
      formatDays([
        { start: 1, end: 5 },
        { start: 8, end: 12 },
      ]),
    ).toBe("Day1〜5・8〜12");
    expect(formatDays([])).toBe("");
  });

  it("書いた形を読み直すと同じ", () => {
    const ranges = [
      { start: 1, end: 1 },
      { start: 8, end: 8 },
      { start: 15, end: 21 },
    ];
    expect(parseDays(formatDays(ranges))).toEqual({ ok: true, value: ranges });
  });
});

describe("parseList / formatList（言い方・用語の一覧）", () => {
  it("「、」「,」「/」「改行」で区切り、空を落とす（「・」は区切らない）", () => {
    expect(parseList("下痢、 お腹がゆるい,,手のひら・足の裏／悪心\n")).toEqual([
      "下痢",
      "お腹がゆるい",
      "手のひら・足の裏",
      "悪心",
    ]);
    expect(parseList(" ")).toEqual([]);
  });

  it("「、」でつなぐ", () => {
    expect(formatList(["悪心", "嘔吐"])).toBe("悪心、嘔吐");
  });
});

describe("parseWholeNumber", () => {
  it("整数（全角も）・空は null・それ以外は失敗", () => {
    expect(parseWholeNumber("14")).toEqual({ ok: true, value: 14 });
    expect(parseWholeNumber("２１")).toEqual({ ok: true, value: 21 });
    expect(parseWholeNumber("")).toEqual({ ok: true, value: null });
    expect(parseWholeNumber("14日").ok).toBe(false);
    expect(parseWholeNumber("1.5").ok).toBe(false);
  });
});

describe("emptyValueOf（確認の「削除」で欄を空にする値）", () => {
  it.each([
    ["drugs.d-x.days", []],
    ["side_effects.se-x.phrases", []],
    ["side_effects.se-x.ctcae_terms", []],
    ["notes", ""],
    ["basic.target", null],
    ["basic.cycle_days", null],
    ["drugs.d-x.times_per_day", null],
    ["questions.q-x.text", null],
  ])("%s → %j", (fieldId, value) => {
    expect(emptyValueOf(fieldId)).toEqual(value);
  });
});

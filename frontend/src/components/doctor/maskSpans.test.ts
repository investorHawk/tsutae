import { describe, expect, it } from "vitest";
import {
  addSpan,
  mergeSpans,
  removeSpanAt,
  sameSpans,
  splitByMasks,
  toCodePoint,
} from "./maskSpans";

describe("mergeSpans", () => {
  it("並べ替え、重なり・隣り合う区間をまとめる", () => {
    expect(
      mergeSpans([
        { start: 5, end: 7 },
        { start: 0, end: 2 },
        { start: 1, end: 3 },
        { start: 7, end: 8 },
      ]),
    ).toEqual([
      { start: 0, end: 3 },
      { start: 5, end: 8 },
    ]);
  });

  it("空・逆順の区間は捨てる", () => {
    expect(
      mergeSpans([
        { start: 2, end: 2 },
        { start: 4, end: 3 },
      ]),
    ).toEqual([]);
  });

  it("引数を書き換えない", () => {
    const spans = [
      { start: 5, end: 7 },
      { start: 0, end: 2 },
    ];
    mergeSpans(spans);
    expect(spans[0]).toEqual({ start: 5, end: 7 });
  });
});

describe("addSpan / removeSpanAt", () => {
  it("選んだ範囲を足す（伏せた区間と重なればまとめる）", () => {
    const base = [{ start: 0, end: 2 }];
    expect(addSpan(base, { start: 1, end: 4 })).toEqual([{ start: 0, end: 4 }]);
    expect(addSpan(base, { start: 5, end: 6 })).toEqual([
      { start: 0, end: 2 },
      { start: 5, end: 6 },
    ]);
    expect(base).toEqual([{ start: 0, end: 2 }]);
  });

  it("伏せた区間の中だけを選んでも変わらない", () => {
    expect(addSpan([{ start: 0, end: 4 }], { start: 1, end: 2 })).toEqual([
      { start: 0, end: 4 },
    ]);
  });

  it("押した区間だけを戻す", () => {
    const spans = [
      { start: 0, end: 2 },
      { start: 5, end: 6 },
    ];
    expect(removeSpanAt(spans, 5)).toEqual([{ start: 0, end: 2 }]);
    expect(spans).toHaveLength(2);
  });
});

describe("sameSpans", () => {
  it("同じ並びなら true", () => {
    expect(sameSpans([{ start: 0, end: 1 }], [{ start: 0, end: 1 }])).toBe(
      true,
    );
    expect(sameSpans([{ start: 0, end: 1 }], [])).toBe(false);
  });
});

describe("splitByMasks", () => {
  it("伏せた区間と、そうでない区間に分ける（位置は code point）", () => {
    expect(splitByMasks("😀磯鷲さん", [{ start: 1, end: 3 }])).toEqual([
      { text: "😀", start: 0, end: 1, masked: false },
      { text: "磯鷲", start: 1, end: 3, masked: true },
      { text: "さん", start: 3, end: 5, masked: false },
    ]);
  });

  it("区間が無ければ全体が1つ", () => {
    expect(splitByMasks("あいう", [])).toEqual([
      { text: "あいう", start: 0, end: 3, masked: false },
    ]);
  });
});

describe("toCodePoint", () => {
  it("UTF-16 の位置を code point に直す（サロゲートペアを1字と数える）", () => {
    expect(toCodePoint("😀磯鷲", 0)).toBe(0);
    expect(toCodePoint("😀磯鷲", 2)).toBe(1);
    expect(toCodePoint("😀磯鷲", 3)).toBe(2);
    expect(toCodePoint("abc", 99)).toBe(3);
  });
});

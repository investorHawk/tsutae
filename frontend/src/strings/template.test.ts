import { describe, expect, it } from "vitest";
import { fillTemplate } from "./template";

describe("fillTemplate", () => {
  it("{name} を値で置き換える（数も文字にする）", () => {
    expect(
      fillTemplate("{month}/{day} ({weekday})", {
        month: 11,
        day: 9,
        weekday: "Mon",
      }),
    ).toBe("11/9 (Mon)");
  });

  it("同じ名前は全て置き換える", () => {
    expect(fillTemplate("{a}-{a}", { a: "x" })).toBe("x-x");
  });

  it("値の無い名前はそのまま残す（定型文の書き間違いを隠さない）", () => {
    expect(fillTemplate("{a} {b}", { a: "x" })).toBe("x {b}");
  });

  it("値の中の {x} は置き換えない（1回だけ置き換える）", () => {
    expect(fillTemplate("{a}{b}", { a: "{b}", b: "y" })).toBe("{b}y");
  });
});

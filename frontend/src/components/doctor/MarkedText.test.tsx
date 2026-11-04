import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MarkedText, { splitMarks } from "./MarkedText";

describe("splitMarks", () => {
  it("印の前・印・後に切り分ける", () => {
    expect(splitMarks("磯鷲さんにもらった", [{ start: 0, end: 4 }])).toEqual([
      { text: "磯鷲さん", marked: true },
      { text: "にもらった", marked: false },
    ]);
  });

  it("位置は code point で数える（絵文字を割らない）", () => {
    expect(splitMarks("😀磯鷲さん", [{ start: 1, end: 5 }])).toEqual([
      { text: "😀", marked: false },
      { text: "磯鷲さん", marked: true },
    ]);
  });

  it("印が無ければ全体を1つ", () => {
    expect(splitMarks("おなか", [])).toEqual([
      { text: "おなか", marked: false },
    ]);
  });

  it("範囲の外・重なる印は無視して、文は欠かさない", () => {
    const pieces = splitMarks("あいうえお", [
      { start: 1, end: 3 },
      { start: 2, end: 4 },
      { start: 4, end: 99 },
    ]);
    expect(pieces.map((p) => p.text).join("")).toBe("あいうえお");
    expect(pieces.filter((p) => p.marked).map((p) => p.text)).toEqual(["いう"]);
  });
});

describe("MarkedText", () => {
  it("印の部分を <mark> で描く", () => {
    const { container } = render(
      <p>
        <MarkedText
          text="電話 1234567 と磯鷲さん"
          marks={[
            { start: 3, end: 10 },
            { start: 12, end: 16 },
          ]}
        />
      </p>,
    );
    const marks = Array.from(container.querySelectorAll("mark")).map(
      (m) => m.textContent,
    );
    expect(marks).toEqual(["1234567", "磯鷲さん"]);
    expect(container).toHaveTextContent("電話 1234567 と磯鷲さん");
  });
});

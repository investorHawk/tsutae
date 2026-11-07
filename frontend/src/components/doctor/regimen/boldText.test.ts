import { describe, expect, it } from "vitest";
import { boldSegments } from "./boldText";

describe("boldSegments", () => {
  it("記号の無い文は1つの区切り（太字でない）", () => {
    expect(boldSegments("フォームを作りました")).toEqual([
      { text: "フォームを作りました", bold: false },
    ]);
  });

  it("空の文は区切りなし", () => {
    expect(boldSegments("")).toEqual([]);
  });

  it("**…** を太字の区切りにする（記号は外す）", () => {
    expect(boldSegments("**FOLFIRI＋BV** のフォームです")).toEqual([
      { text: "FOLFIRI＋BV", bold: true },
      { text: " のフォームです", bold: false },
    ]);
  });

  it("1行に2つ・行頭の箇条書きの中・改行をはさんだ別の行", () => {
    expect(
      boldSegments("**基本**と**質問**\n- **識別名:** FOLFIRI-BV"),
    ).toEqual([
      { text: "基本", bold: true },
      { text: "と", bold: false },
      { text: "質問", bold: true },
      { text: "\n- ", bold: false },
      { text: "識別名:", bold: true },
      { text: " FOLFIRI-BV", bold: false },
    ]);
  });

  it("対になっていない ** は記号のまま", () => {
    expect(boldSegments("**閉じない")).toEqual([
      { text: "**閉じない", bold: false },
    ]);
    expect(boldSegments("**a** と **b")).toEqual([
      { text: "a", bold: true },
      { text: " と **b", bold: false },
    ]);
  });

  it("空の **** と、中が * だけのものは記号のまま", () => {
    expect(boldSegments("前****後")).toEqual([
      { text: "前****後", bold: false },
    ]);
    expect(boldSegments("*****")).toEqual([{ text: "*****", bold: false }]);
  });

  it("改行をまたぐ **…** は記号のまま", () => {
    expect(boldSegments("**一行目\n二行目**")).toEqual([
      { text: "**一行目\n二行目**", bold: false },
    ]);
  });

  it("1つの * は太字にしない（斜体は扱わない）", () => {
    expect(boldSegments("*注意* と 2*3")).toEqual([
      { text: "*注意* と 2*3", bold: false },
    ]);
  });

  it("引数の文を変えない（同じ入力に同じ出力）", () => {
    const text = "**a**";
    expect(boldSegments(text)).toEqual(boldSegments(text));
    expect(text).toBe("**a**");
  });
});

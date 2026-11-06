import { describe, expect, it } from "vitest";
import { splitIntroTitle } from "../src/lib/introTitle";

describe("splitIntroTitle（intro の題を大きな数字と副題に分ける）", () => {
  it("最初の読点で分け、頭の数字を取り出す", () => {
    expect(splitIntroTitle("25 年間、消化器外科医として癌治療")).toEqual({
      number: "25",
      unit: "年間",
      sub: "消化器外科医として癌治療",
    });
  });

  it("頭が数字でなければ number は空で、頭全体を unit にする", () => {
    expect(splitIntroTitle("長年、外科医")).toEqual({
      number: "",
      unit: "長年",
      sub: "外科医",
    });
  });

  it("読点が無ければ sub は空", () => {
    expect(splitIntroTitle("10 年")).toEqual({
      number: "10",
      unit: "年",
      sub: "",
    });
    expect(splitIntroTitle("")).toEqual({ number: "", unit: "", sub: "" });
  });
});

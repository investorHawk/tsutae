import { describe, expect, it } from "vitest";
import { appendDrugName, showsDrugChips } from "./chatDrugNames";

describe("appendDrugName", () => {
  it("空なら名前だけ", () => {
    expect(appendDrugName("", "パクリタキセル", 100)).toBe("パクリタキセル");
  });

  it("空でなければ「・」でつなぐ", () => {
    expect(appendDrugName("パクリタキセル", "ラムシルマブ", 100)).toBe(
      "パクリタキセル・ラムシルマブ",
    );
  });

  it.each(["A・", "A、", "A,", "A，", "A。", "A：", "A ", "A　", "A\n", "A＋"])(
    "末尾が既に区切りなら足さない（%j）",
    (text) => {
      expect(appendDrugName(text, "B", 100)).toBe(`${text}B`);
    },
  );

  it("上限ちょうどなら足し、超えるなら元のまま", () => {
    expect(appendDrugName("AB", "CD", 5)).toBe("AB・CD");
    expect(appendDrugName("AB", "CDE", 5)).toBe("AB");
    expect(appendDrugName("", "ABCDEF", 5)).toBe("");
    expect(appendDrugName("ABC・", "DE", 5)).toBe("ABC・");
  });
});

describe("showsDrugChips", () => {
  const draft = { base_version: null, chat: [] };

  it("新しいレジメンで会話が無く、候補があるときだけ", () => {
    expect(showsDrugChips(draft, ["A"])).toBe(true);
    expect(showsDrugChips(draft, [])).toBe(false);
    expect(showsDrugChips({ ...draft, base_version: 1 }, ["A"])).toBe(false);
    expect(showsDrugChips({ ...draft, chat: [{}] }, ["A"])).toBe(false);
  });
});

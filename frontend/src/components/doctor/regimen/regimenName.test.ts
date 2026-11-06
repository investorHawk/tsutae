import { describe, expect, it } from "vitest";
import { UNNAMED_REGIMEN, filledName, regimenNameOf } from "./regimenName";

describe("regimenName", () => {
  it("名前が無いときの文言は「新しいレジメン」", () => {
    expect(UNNAMED_REGIMEN).toBe("新しいレジメン");
  });

  it.each([null, undefined, "", "  ", "　"])("空（%j）は名前なし", (name) => {
    expect(filledName(name)).toBeNull();
    expect(regimenNameOf(name)).toBe("新しいレジメン");
  });

  it("入っている名前はそのまま", () => {
    expect(filledName("FOLFIRI＋BV")).toBe("FOLFIRI＋BV");
    expect(regimenNameOf("FOLFIRI＋BV")).toBe("FOLFIRI＋BV");
  });
});

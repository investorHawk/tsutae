import { describe, expect, it } from "vitest";
import {
  isReportFormatSkill,
  skillDisplayName,
  skillOptionLabel,
  versionLabel,
} from "./skillLabels";

// D5-1: Skill の内部名（regimen-folfox など）ではなく、医師向けの呼び名で出す
describe("skillDisplayName", () => {
  it.each([
    ["regimen-folfox", "FOLFOX の質問集"],
    ["regimen-capox", "CAPOX の質問集"],
    ["report-format-default", "レポートの形式"],
  ])("%s → %s", (name, label) => {
    expect(skillDisplayName(name)).toBe(label);
  });

  it("知らない regimen はレジメン名を大文字にして「の質問集」", () => {
    expect(skillDisplayName("regimen-sox")).toBe("SOX の質問集");
    expect(skillDisplayName("regimen-xelox-2")).toBe("XELOX-2 の質問集");
  });

  it("既定でないレポートの形式は名前を添える", () => {
    expect(skillDisplayName("report-format-short")).toBe(
      "レポートの形式（short）",
    );
  });

  it("書式に合わない名前はそのまま", () => {
    expect(skillDisplayName("something")).toBe("something");
    expect(skillDisplayName("regimen-")).toBe("regimen-");
  });
});

describe("versionLabel", () => {
  it("version を「第N版」にする", () => {
    expect(versionLabel(1)).toBe("第1版");
    expect(versionLabel(12)).toBe("第12版");
  });
});

describe("skillOptionLabel", () => {
  it("呼び名と版", () => {
    expect(skillOptionLabel({ name: "regimen-folfox", version: 1 })).toBe(
      "FOLFOX の質問集（第1版）",
    );
    expect(
      skillOptionLabel({ name: "report-format-default", version: 3 }),
    ).toBe("レポートの形式（第3版）");
  });
});

describe("isReportFormatSkill", () => {
  it("report-format-* だけ（レジメンは D4 レジメンの画面で直す）", () => {
    expect(isReportFormatSkill("report-format-default")).toBe(true);
    expect(isReportFormatSkill("report-format-short")).toBe(true);
    expect(isReportFormatSkill("regimen-folfox")).toBe(false);
    expect(isReportFormatSkill("regimen-capox")).toBe(false);
    expect(isReportFormatSkill("report-format-")).toBe(false);
  });
});

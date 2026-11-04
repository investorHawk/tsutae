import { describe, expect, it } from "vitest";
import type {
  RegimenDraftSummary,
  RegimenDraftsResponse,
} from "../../../api/regimenTypes";
import type { RegimensResponse } from "../../../api/types";
import { fixtureBody } from "../../../test/apiFixtures";
import { regimenTabs } from "./tabList";

const REGIMENS = (fixtureBody("doctor_regimens") as RegimensResponse).regimens;
const NEW_DRAFT = (
  fixtureBody("doctor_regimen_drafts") as RegimenDraftsResponse
).drafts[0];

describe("regimenTabs", () => {
  it("採用済み（表示名 版N）→ 新規の下書き → ＋ 新しいレジメン", () => {
    const tabs = regimenTabs(REGIMENS, [NEW_DRAFT]);
    expect(tabs.map((t) => [t.label, t.sub])).toEqual([
      ["FOLFOX", "版 1"],
      ["CAPOX", "版 1"],
      ["FOLFIRI＋BV", "下書き（新規）"],
      ["＋ 新しいレジメン", ""],
    ]);
  });

  it("既存のレジメンに開いた下書きがあれば「版 N+1 の下書き」", () => {
    const open: RegimenDraftSummary = {
      ...NEW_DRAFT,
      id: 2,
      regimen: "CAPOX",
      skill_name: "regimen-capox",
      display_name: "CAPOX",
      base_version: 1,
      version: 2,
    };
    const tabs = regimenTabs(REGIMENS, [open]);
    expect(tabs[1]).toMatchObject({ label: "CAPOX", sub: "版 2 の下書き" });
    expect(tabs).toHaveLength(3);
  });

  it("名前の無い新規の下書き", () => {
    const tabs = regimenTabs([], [{ ...NEW_DRAFT, display_name: null }]);
    expect(tabs[0].label).toBe("名前のないレジメン");
  });
});

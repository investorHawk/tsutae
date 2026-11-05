import { describe, expect, it } from "vitest";
import { FOOTAGE, FOOTAGE_IDS } from "../src/footage";
import { footageFiles, screenFiles } from "../src/footage.generated";

describe("撮影リストと manifest", () => {
  it("撮影リストは F1〜F10 の 10 本", () => {
    expect(FOOTAGE_IDS).toEqual([
      "F1",
      "F2",
      "F3",
      "F4",
      "F5",
      "F6",
      "F7",
      "F8",
      "F9",
      "F10",
    ]);
    for (const id of FOOTAGE_IDS) expect(FOOTAGE[id].id).toBe(id);
  });

  it("manifest の録画は既知の id で public/footage の下を指す", () => {
    for (const [id, path] of Object.entries(footageFiles)) {
      expect(FOOTAGE_IDS).toContain(id);
      expect(path).toMatch(/^footage\/F\d+([_-].*)?\.(mp4|mov)$/i);
    }
  });

  it("manifest の静止画は既知の id で public/screens/F<n>-<k>.png を k の順に指す", () => {
    for (const [id, paths] of Object.entries(screenFiles)) {
      expect(FOOTAGE_IDS).toContain(id);
      expect(paths?.length, id).toBeGreaterThan(0);
      const ks = (paths ?? []).map((p) => {
        const m = /^screens\/(F\d+)-(\d+)\.png$/.exec(p);
        expect(m, p).not.toBeNull();
        expect(m?.[1], p).toBe(id);
        return Number(m?.[2]);
      });
      expect(ks).toEqual([...ks].sort((a, b) => a - b));
    }
  });

  it("撮影済みの静止画（F1・F2・F4・F8・F9）が manifest に載る", () => {
    expect(screenFiles.F1).toEqual(["screens/F1-1.png", "screens/F1-2.png"]);
    expect(screenFiles.F2).toEqual([
      "screens/F2-1.png",
      "screens/F2-2.png",
      "screens/F2-3.png",
    ]);
    expect(screenFiles.F4).toHaveLength(2);
    expect(screenFiles.F8).toHaveLength(3);
    expect(screenFiles.F9).toEqual(["screens/F9-1.png"]);
  });
});

import { describe, expect, it } from "vitest";
import { FOOTAGE, FOOTAGE_IDS } from "../src/footage";
import { audioFiles, footageFiles } from "../src/footage.generated";

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

  it("manifest の音声は narration-a|b|c だけ", () => {
    for (const a of audioFiles) expect(a).toMatch(/^narration-[abc]$/);
  });
});

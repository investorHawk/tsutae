import { describe, expect, it } from "vitest";
import narration from "../scripts/narration.json";
import { scenesB } from "../src/storyboards";

describe("ナレーション音声の台本（scripts/narration.json）", () => {
  it("場面の id の並びが scenesB と同じ", () => {
    expect(narration.scenes.map((s) => s.id)).toEqual(scenesB.map((s) => s.id));
  });

  it("text（字幕）が scenesB の narration と完全に一致する", () => {
    narration.scenes.forEach((s, i) => {
      expect(s.text, s.id).toBe(scenesB[i].narration);
    });
  });

  it("read（読み上げ用）が空でない", () => {
    for (const s of narration.scenes) {
      expect(s.read.trim().length, s.id).toBeGreaterThan(0);
    }
  });

  it("read は「A4」を「エーヨン」に読み替え、読みにくい記号を残さない", () => {
    for (const s of narration.scenes) {
      expect(s.read, s.id).not.toContain("A4");
      expect(s.read, s.id).not.toMatch(/[…・]/);
    }
    const a4 = narration.scenes.filter((s) => s.text.includes("A4"));
    expect(a4.length).toBeGreaterThan(0);
    for (const s of a4) expect(s.read, s.id).toContain("エーヨン");
  });

  it("話者 id は整数", () => {
    expect(Number.isInteger(narration.speaker)).toBe(true);
  });
});

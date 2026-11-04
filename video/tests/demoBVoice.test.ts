import { describe, expect, it } from "vitest";
import { footageSegments, totalSeconds } from "../src/lib/timeline";
import {
  demoBVoice,
  VOICE_TIMING_B,
  voiceClipsB,
} from "../src/storyboards/bVoice";
import { scenesB } from "../src/storyboards";

const { lead, tail, floors = {} } = VOICE_TIMING_B;
const clipOf = (id: string) => voiceClipsB.find((c) => c.id === id);

describe("DemoBVoice（案 B に声をつけた版）", () => {
  it("Composition の id と案", () => {
    expect(demoBVoice.compositionId).toBe("DemoBVoice");
    expect(demoBVoice.variant).toBe("b");
  });

  it("場面の id が scenesB と同じ順", () => {
    expect(demoBVoice.scenes.map((s) => s.id)).toEqual(
      scenesB.map((s) => s.id),
    );
  });

  it("声の一覧は scenesB の場面 id だけを指し、voice/b/<id>.wav に置く", () => {
    const ids = scenesB.map((s) => s.id);
    for (const c of voiceClipsB) {
      expect(ids).toContain(c.id);
      expect(c.file).toBe(`voice/b/${c.id}.wav`);
      expect(c.seconds, c.id).toBeGreaterThan(0);
    }
  });

  it("声のある場面は lead + 声 + tail 秒以上、声の無い場面は元の秒", () => {
    demoBVoice.scenes.forEach((s, i) => {
      const c = clipOf(s.id);
      if (c) {
        expect(s.seconds, s.id).toBeGreaterThanOrEqual(lead + c.seconds + tail);
        expect(s.voice?.file, s.id).toBe(c.file);
      } else {
        expect(s.seconds, s.id).toBe(scenesB[i].seconds);
        expect(s.voice, s.id).toBeUndefined();
      }
    });
  });

  it("split の合計＝場面の秒", () => {
    for (const s of demoBVoice.scenes.filter((x) => x.props?.split)) {
      const sum = footageSegments(s).reduce((a, g) => a + g.seconds, 0);
      expect(sum, s.id).toBeCloseTo(s.seconds, 6);
    }
  });

  it("coldopen と closing はアニメが潰れない下限を持ち、それを下回らない", () => {
    expect(floors["b01-coldopen"]).toBeGreaterThanOrEqual(7);
    expect(floors["b10-closing"]).toBeGreaterThanOrEqual(14);
    for (const s of demoBVoice.scenes) {
      const floor = floors[s.id];
      if (floor !== undefined && clipOf(s.id)) {
        expect(s.seconds, s.id).toBeGreaterThanOrEqual(floor);
      }
    }
    for (const id of demoBVoice.floored) expect(floors[id]).toBeDefined();
  });

  it("声が空なら scenesB と同じ合計（150 秒）", () => {
    if (voiceClipsB.length === 0) {
      expect(totalSeconds(demoBVoice.scenes)).toBe(150);
    } else {
      expect(totalSeconds(demoBVoice.scenes)).toBeGreaterThan(0);
    }
  });
});

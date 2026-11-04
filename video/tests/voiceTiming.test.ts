import { describe, expect, it } from "vitest";
import {
  applyVoiceTiming,
  footageSegments,
  totalSeconds,
} from "../src/lib/timeline";
import { scenesB } from "../src/storyboards";
import type { Scene, VoiceClip } from "../src/types";

const OPTS = { lead: 0.5, tail: 0.9 };

const scene = (over: Partial<Scene> & { id: string }): Scene => ({
  seconds: 10,
  kind: "after",
  narration: "テスト",
  ...over,
});

const clip = (id: string, seconds: number): VoiceClip => ({
  id,
  file: `voice/b/${id}.wav`,
  seconds,
});

describe("applyVoiceTiming（声の長さから場面の秒を決める）", () => {
  it("声のある場面は lead + 声 + tail 秒、声の無い場面は元の秒", () => {
    const scenes = [scene({ id: "s1" }), scene({ id: "s2", seconds: 7 })];
    const { scenes: out } = applyVoiceTiming(scenes, [clip("s1", 4.2)], OPTS);
    expect(out[0].seconds).toBeCloseTo(5.6, 2);
    expect(out[0].seconds).toBeGreaterThanOrEqual(0.5 + 4.2 + 0.9);
    expect(out[1].seconds).toBe(7);
    expect(out[1].voice).toBeUndefined();
  });

  it("声の情報（ファイル・開始秒・長さ）を場面に持たせる", () => {
    const { scenes: out } = applyVoiceTiming(
      [scene({ id: "s1" })],
      [clip("s1", 3.333)],
      OPTS,
    );
    expect(out[0].voice).toEqual({
      file: "voice/b/s1.wav",
      leadSeconds: 0.5,
      seconds: 3.333,
    });
  });

  it("秒は 1/1000 秒に切り上げ、lead + 声 + tail を下回らない", () => {
    const { scenes: out } = applyVoiceTiming(
      [scene({ id: "s1" })],
      [clip("s1", 2.1234)],
      OPTS,
    );
    expect(out[0].seconds).toBe(3.524);
  });

  it("split は合計が新しい秒になるよう比率で縮める", () => {
    const s = scene({
      id: "s1",
      kind: "footage",
      seconds: 14,
      footage: ["F1", "F2"],
      props: { split: [8, 6], callouts: ["a", null] },
    });
    const { scenes: out } = applyVoiceTiming([s], [clip("s1", 5.6)], OPTS);
    const split = out[0].props?.split ?? [];
    expect(split).toHaveLength(2);
    expect(split[0] + split[1]).toBeCloseTo(out[0].seconds, 6);
    expect(split[0] / split[1]).toBeCloseTo(8 / 6, 2);
    expect(out[0].props?.callouts).toEqual(["a", null]);
    const segs = footageSegments(out[0]);
    expect(segs[1].fromSeconds + segs[1].seconds).toBeCloseTo(
      out[0].seconds,
      6,
    );
  });

  it("下限（floors）に当たった場面はその秒になり、floored に載る", () => {
    const scenes = [scene({ id: "open", seconds: 8 }), scene({ id: "x" })];
    const { scenes: out, floored } = applyVoiceTiming(
      scenes,
      [clip("open", 2), clip("x", 2)],
      { ...OPTS, floors: { open: 7, x: 1 } },
    );
    expect(out[0].seconds).toBe(7);
    expect(out[1].seconds).toBeCloseTo(3.4, 2);
    expect(floored).toEqual(["open"]);
  });

  it("引数（場面・props・split）を変更しない", () => {
    const before = structuredClone(scenesB);
    const clips = scenesB.map((s) => clip(s.id, 3));
    const { scenes: out } = applyVoiceTiming(scenesB, clips, OPTS);
    expect(scenesB).toEqual(before);
    expect(out[3]).not.toBe(scenesB[3]);
    expect(out[3].props).not.toBe(scenesB[3].props);
  });

  it("声が空なら秒は元のまま（合計 150 秒）", () => {
    const { scenes: out, floored } = applyVoiceTiming(scenesB, [], OPTS);
    expect(totalSeconds(out)).toBe(150);
    expect(out.map((s) => s.seconds)).toEqual(scenesB.map((s) => s.seconds));
    expect(floored).toEqual([]);
  });

  it("声の秒が負や数でないときはエラーにする", () => {
    expect(() =>
      applyVoiceTiming([scene({ id: "s1" })], [clip("s1", -1)], OPTS),
    ).toThrow(/s1/);
    expect(() =>
      applyVoiceTiming([scene({ id: "s1" })], [clip("s1", NaN)], OPTS),
    ).toThrow(/s1/);
  });
});

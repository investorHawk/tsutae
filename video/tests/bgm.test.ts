import { describe, expect, it } from "vitest";
import { bgmFile } from "../src/footage.generated";
import {
  BGM_VOLUME,
  bgmVolumeAt,
  voiceFrames,
  voiceRanges,
  type FrameRange,
} from "../src/lib/bgm";
import { layoutScenes } from "../src/lib/timeline";
import { STORYBOARDS } from "../src/storyboards";
import { demoBVoice } from "../src/storyboards/bVoice";
import { FPS } from "../src/theme";
import type { Scene } from "../src/types";

const fps = 30;
const { base, ducked, rampSeconds, fadeInSeconds, fadeOutSeconds } = BGM_VOLUME;

const scene = (id: string, seconds: number, voice?: Scene["voice"]): Scene => ({
  id,
  seconds,
  kind: "title",
  narration: "",
  ...(voice ? { voice } : {}),
});

/** 1 フレームあたりの変化の上限（smoothstep の最大傾き 1.5 倍＋フェードの傾き） */
const maxStep =
  (1.5 * (base - ducked)) / (rampSeconds * fps) +
  base / (Math.min(fadeInSeconds, fadeOutSeconds) * fps);

const volumes = (total: number, ranges: FrameRange[]) =>
  Array.from({ length: total }, (_, f) => bgmVolumeAt(f, ranges, total, fps));

describe("BGM の音量の定数", () => {
  it("声の区間は基本より小さく、どちらも 0〜1", () => {
    expect(ducked).toBeGreaterThan(0);
    expect(ducked).toBeLessThan(base);
    expect(base).toBeLessThanOrEqual(1);
    expect(rampSeconds).toBeGreaterThanOrEqual(0.3);
    expect(rampSeconds).toBeLessThanOrEqual(0.4);
  });
});

describe("voiceFrames / voiceRanges（声が鳴る区間）", () => {
  it("場面の中の区間は lead から lead + 声の秒（フレームに丸める）", () => {
    expect(
      voiceFrames({ file: "x.wav", leadSeconds: 0.5, seconds: 3.645 }, fps),
    ).toEqual({ from: 15, to: 124 });
  });

  it("場面の頭のフレームを足した絶対フレームで、声のある場面だけ返す", () => {
    const timed = layoutScenes(
      [
        scene("a", 5, { file: "a.wav", leadSeconds: 0.5, seconds: 2 }),
        scene("b", 4),
        scene("c", 6, { file: "c.wav", leadSeconds: 0.5, seconds: 4 }),
      ],
      fps,
    );
    expect(voiceRanges(timed, fps)).toEqual([
      { from: 15, to: 75 },
      { from: 285, to: 405 },
    ]);
  });

  it("声が無ければ空", () => {
    expect(voiceRanges(layoutScenes([scene("a", 5)], fps), fps)).toEqual([]);
  });

  it("引数を変更しない", () => {
    const timed = layoutScenes(
      [scene("a", 5, { file: "a.wav", leadSeconds: 0.5, seconds: 2 })],
      fps,
    );
    const before = JSON.stringify(timed);
    voiceRanges(timed, fps);
    expect(JSON.stringify(timed)).toBe(before);
  });
});

describe("bgmVolumeAt（frame ごとの BGM の音量）", () => {
  const total = 600;

  it("ranges が空ならフェードの外は基本音量", () => {
    expect(bgmVolumeAt(300, [], total, fps)).toBeCloseTo(base, 10);
  });

  it("声の区間の中は下げた音量", () => {
    const ranges = [{ from: 100, to: 200 }];
    for (const f of [100, 150, 199]) {
      expect(bgmVolumeAt(f, ranges, total, fps), String(f)).toBeCloseTo(
        ducked,
        10,
      );
    }
  });

  it("声の区間から ramp 秒より離れれば基本音量に戻る", () => {
    const ranges = [{ from: 100, to: 200 }];
    const ramp = Math.ceil(rampSeconds * fps);
    expect(bgmVolumeAt(100 - ramp - 1, ranges, total, fps)).toBeCloseTo(
      base,
      10,
    );
    expect(bgmVolumeAt(200 + ramp + 1, ranges, total, fps)).toBeCloseTo(
      base,
      10,
    );
    const mid = bgmVolumeAt(200 + Math.floor(ramp / 2), ranges, total, fps);
    expect(mid).toBeGreaterThan(ducked);
    expect(mid).toBeLessThan(base);
  });

  it("冒頭は 0 から fadeIn 秒で上がる", () => {
    expect(bgmVolumeAt(0, [], total, fps)).toBe(0);
    const half = bgmVolumeAt(
      Math.round((fadeInSeconds * fps) / 2),
      [],
      total,
      fps,
    );
    expect(half).toBeGreaterThan(0);
    expect(half).toBeLessThan(base);
    expect(bgmVolumeAt(fadeInSeconds * fps, [], total, fps)).toBeCloseTo(
      base,
      10,
    );
  });

  it("最後の fadeOut 秒で下がり、最後のフレームはちょうど 0", () => {
    const start = total - 1 - fadeOutSeconds * fps;
    expect(bgmVolumeAt(start, [], total, fps)).toBeCloseTo(base, 10);
    expect(bgmVolumeAt(total - 1, [], total, fps)).toBe(0);
    expect(bgmVolumeAt(total + 10, [], total, fps)).toBe(0);
  });

  it("隣のフレームとの差が小さい（切り替えが滑らか）", () => {
    const ranges = [
      { from: 20, to: 120 },
      { from: 140, to: 300 }, // 短い隙間
      { from: 560, to: 600 }, // フェードアウトと重なる
    ];
    const v = volumes(total, ranges);
    for (let f = 1; f < total; f++) {
      expect(Math.abs(v[f] - v[f - 1]), String(f)).toBeLessThanOrEqual(
        maxStep + 1e-12,
      );
    }
  });

  it("短い隙間でも ducked〜base の間に収まり、0 未満にならない", () => {
    const ranges = [
      { from: 100, to: 200 },
      { from: 205, to: 300 },
    ];
    const v = volumes(total, ranges);
    for (let f = 0; f < total; f++) {
      expect(v[f], String(f)).toBeGreaterThanOrEqual(0);
      expect(v[f], String(f)).toBeLessThanOrEqual(base + 1e-12);
    }
    for (let f = 100; f < 300; f++) {
      expect(v[f], String(f)).toBeGreaterThanOrEqual(ducked - 1e-12);
    }
  });

  it("totalFrames が fade より短くても NaN にならない", () => {
    for (let f = 0; f < 10; f++) {
      expect(Number.isFinite(bgmVolumeAt(f, [], 10, fps))).toBe(true);
    }
  });
});

describe("BGM をつけるのは DemoBVoice だけ", () => {
  it("3 案には BGM の印が無い", () => {
    for (const sb of STORYBOARDS) expect(sb.bgm, sb.compositionId).toBeFalsy();
  });

  it("DemoBVoice には BGM の印がある", () => {
    expect(demoBVoice.bgm).toBe(true);
  });

  it("DemoBVoice の声の区間は重ならず、長さの中に収まる", () => {
    const timed = layoutScenes(demoBVoice.scenes, FPS);
    const ranges = voiceRanges(timed, FPS);
    const total = timed.reduce((s, t) => s + t.durationInFrames, 0);
    ranges.forEach((r, i) => {
      expect(r.to).toBeGreaterThan(r.from);
      expect(r.to).toBeLessThanOrEqual(total);
      if (i > 0) expect(r.from).toBeGreaterThanOrEqual(ranges[i - 1].to);
    });
  });

  it("manifest の bgmFile は null か voice/bgm.wav", () => {
    expect([null, "voice/bgm.wav"]).toContain(bgmFile);
  });
});

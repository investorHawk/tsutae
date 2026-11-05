import { describe, expect, it } from "vitest";
import { bgmFile } from "../src/footage.generated";
import { BGM_VOLUME, bgmVolumeAt } from "../src/lib/bgm";
import { STORYBOARDS } from "../src/storyboards";

const fps = 30;
const { base, fadeInSeconds, fadeOutSeconds } = BGM_VOLUME;

/** 1 フレームあたりの変化の上限（いちばん急なフェードの傾き） */
const maxStep = base / (Math.min(fadeInSeconds, fadeOutSeconds) * fps);

describe("BGM の音量の定数", () => {
  it("基本音量は 0〜1", () => {
    expect(base).toBeGreaterThan(0);
    expect(base).toBeLessThanOrEqual(1);
  });

  it("基本音量と両端のフェードだけを持つ", () => {
    expect(Object.keys(BGM_VOLUME).sort()).toEqual([
      "base",
      "fadeInSeconds",
      "fadeOutSeconds",
    ]);
  });
});

describe("bgmVolumeAt（frame ごとの BGM の音量）", () => {
  const total = 600;

  it("フェードの外は基本音量", () => {
    expect(bgmVolumeAt(300, total, fps)).toBeCloseTo(base, 10);
  });

  it("冒頭は 0 から fadeIn 秒で上がる", () => {
    expect(bgmVolumeAt(0, total, fps)).toBe(0);
    const half = bgmVolumeAt(Math.round((fadeInSeconds * fps) / 2), total, fps);
    expect(half).toBeGreaterThan(0);
    expect(half).toBeLessThan(base);
    expect(bgmVolumeAt(fadeInSeconds * fps, total, fps)).toBeCloseTo(base, 10);
  });

  it("最後の fadeOut 秒で下がり、最後のフレームはちょうど 0", () => {
    const start = total - 1 - fadeOutSeconds * fps;
    expect(bgmVolumeAt(start, total, fps)).toBeCloseTo(base, 10);
    expect(bgmVolumeAt(total - 1, total, fps)).toBe(0);
    expect(bgmVolumeAt(total + 10, total, fps)).toBe(0);
  });

  it("隣のフレームとの差が小さく、0〜base に収まる", () => {
    const v = Array.from({ length: total }, (_, f) =>
      bgmVolumeAt(f, total, fps),
    );
    v.forEach((x, f) => {
      expect(x, String(f)).toBeGreaterThanOrEqual(0);
      expect(x, String(f)).toBeLessThanOrEqual(base + 1e-12);
      if (f > 0) {
        expect(Math.abs(x - v[f - 1]), String(f)).toBeLessThanOrEqual(
          maxStep + 1e-12,
        );
      }
    });
  });

  it("totalFrames が fade より短くても NaN にならない", () => {
    for (let f = 0; f < 10; f++) {
      expect(Number.isFinite(bgmVolumeAt(f, 10, fps))).toBe(true);
    }
  });
});

describe("BGM をつけるのは案 B だけ", () => {
  it("DemoB にだけ BGM の印がある", () => {
    const marked = STORYBOARDS.filter((sb) => sb.bgm === true).map(
      (sb) => sb.compositionId,
    );
    expect(marked).toEqual(["DemoB"]);
  });

  it("manifest の bgmFile は null か audio/bgm.wav", () => {
    expect([null, "audio/bgm.wav"]).toContain(bgmFile);
  });
});

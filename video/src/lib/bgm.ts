// BGM の音量（frame の関数）と、声が鳴る区間の計算。React / remotion を import しない。
import type { SceneVoice } from "../types";
import type { TimedScene } from "./timeline";

/** BGM の音量の定数（調整はここだけ） */
export const BGM_VOLUME = {
  /** 声の無い区間の音量 */
  base: 0.16,
  /** 声が鳴っている区間の音量（ダッキング） */
  ducked: 0.06,
  /** base ⇄ ducked の切り替えにかける秒（声の前後に広げる） */
  rampSeconds: 0.35,
  /** 冒頭のフェードイン（秒） */
  fadeInSeconds: 1,
  /** 最後のフェードアウト（秒）。最後のフレームで 0 */
  fadeOutSeconds: 3,
} as const;

export type BgmVolumeOptions = typeof BGM_VOLUME;

export interface FrameRange {
  /** 声の始まり（含む） */
  from: number;
  /** 声の終わり（含まない） */
  to: number;
}

/** 声の区間（場面の中のフレーム）。Demo の声の配置と同じ丸め */
export const voiceFrames = (voice: SceneVoice, fps: number): FrameRange => ({
  from: Math.round(voice.leadSeconds * fps),
  to: Math.round((voice.leadSeconds + voice.seconds) * fps),
});

/** 声が鳴る区間（動画の頭からの絶対フレーム）。声のある場面だけ */
export const voiceRanges = (timed: TimedScene[], fps: number): FrameRange[] =>
  timed.flatMap(({ scene, from }) => {
    if (!scene.voice) return [];
    const r = voiceFrames(scene.voice, fps);
    return [{ from: from + r.from, to: from + r.to }];
  });

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

const smoothstep = (x: number): number => {
  const t = clamp01(x);
  return t * t * (3 - 2 * t);
};

/** 区間からの距離（フレーム）。中なら 0 */
const distanceTo = (frame: number, r: FrameRange): number => {
  if (frame < r.from) return r.from - frame;
  if (frame >= r.to) return frame - (r.to - 1);
  return 0;
};

/** ダッキングの重み（0 = 基本、1 = 下げ切り）。区間の外は ramp で滑らかに戻す */
const duckWeight = (
  frame: number,
  ranges: FrameRange[],
  rampFrames: number,
): number => {
  if (ranges.length === 0) return 0;
  const d = Math.min(...ranges.map((r) => distanceTo(frame, r)));
  if (d === 0) return 1;
  return rampFrames > 0 ? smoothstep(1 - d / rampFrames) : 0;
};

/** 両端のフェード（0〜1）。最後のフレームでちょうど 0 */
const fadeGain = (
  frame: number,
  totalFrames: number,
  fps: number,
  opts: BgmVolumeOptions,
): number => {
  const inFrames = opts.fadeInSeconds * fps;
  const outFrames = opts.fadeOutSeconds * fps;
  const fadeIn = inFrames > 0 ? clamp01(frame / inFrames) : 1;
  const left = totalFrames - 1 - frame;
  const fadeOut = outFrames > 0 ? clamp01(left / outFrames) : left >= 0 ? 1 : 0;
  return Math.min(fadeIn, fadeOut);
};

/**
 * frame での BGM の音量。基本 base、声の区間は ducked（前後 rampSeconds で滑らかに）、
 * 冒頭 fadeInSeconds でフェードイン、最後 fadeOutSeconds でフェードアウトして 0 で終わる。
 */
export const bgmVolumeAt = (
  frame: number,
  ranges: FrameRange[],
  totalFrames: number,
  fps: number,
  opts: BgmVolumeOptions = BGM_VOLUME,
): number => {
  const w = duckWeight(frame, ranges, opts.rampSeconds * fps);
  const level = opts.base + (opts.ducked - opts.base) * w;
  return level * fadeGain(frame, totalFrames, fps, opts);
};

// BGM の音量（frame の関数）。React / remotion を import しない。

/** BGM の音量の定数（調整はここだけ） */
export const BGM_VOLUME = {
  /** 基本の音量 */
  base: 0.16,
  /** 冒頭のフェードイン（秒） */
  fadeInSeconds: 1,
  /** 最後のフェードアウト（秒）。最後のフレームで 0 */
  fadeOutSeconds: 3,
  /** その案に声（public/voice/）が 1 本でもあるとき、動画全体の音量に掛ける倍率 */
  underVoice: 0.5,
} as const;

export type BgmVolumeOptions = typeof BGM_VOLUME;

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

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
 * frame での BGM の音量。基本 base、冒頭 fadeInSeconds でフェードイン、
 * 最後 fadeOutSeconds でフェードアウトして 0 で終わる。
 * hasVoice（その案に声が 1 本でもある）なら全体を underVoice 倍に下げる（声の区間ごとには変えない）。
 */
export const bgmVolumeAt = (
  frame: number,
  totalFrames: number,
  fps: number,
  hasVoice = false,
  opts: BgmVolumeOptions = BGM_VOLUME,
): number => {
  const level = hasVoice ? opts.base * opts.underVoice : opts.base;
  return level * fadeGain(frame, totalFrames, fps, opts);
};

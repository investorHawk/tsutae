// 静止画のスライド: 区間を枚数で均等に割り、短いクロスフェードとゆっくりしたズームで切り替える。
// React / remotion を import しない（vitest が素で読む）。

/** 切り替えのクロスフェード（フレーム） */
export const SLIDE_FADE_FRAMES = 8;
/** 1 枚を出している間に寄る量（1.0 → 1 + SLIDE_ZOOM） */
export const SLIDE_ZOOM = 0.04;

export interface SlideState {
  visible: boolean;
  opacity: number;
  scale: number;
}

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

/**
 * frame の時点の各画像の状態。新しい画像は前の画像の上に重ねてフェードインし、
 * 重なりきった後に前の画像を消す（画像は不透明なので背景が透けない）。
 */
export const slideStates = (
  count: number,
  totalFrames: number,
  frame: number,
  fade = SLIDE_FADE_FRAMES,
): SlideState[] => {
  if (count <= 0) return [];
  const startOf = (i: number): number => Math.round((i * totalFrames) / count);
  return Array.from({ length: count }, (_, i) => {
    const start = startOf(i);
    const isLast = i === count - 1;
    const hideAt = isLast ? Infinity : startOf(i + 1) + fade;
    const span = startOf(i + 1) - start + (isLast ? 0 : fade);
    const visible = frame >= start && frame < hideAt;
    const opacity = i === 0 ? 1 : clamp01((frame - start) / fade);
    const scale = 1 + SLIDE_ZOOM * clamp01((frame - start) / Math.max(1, span));
    return { visible, opacity: visible ? opacity : 0, scale };
  });
};

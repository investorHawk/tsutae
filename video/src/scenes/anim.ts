import { interpolate, spring } from "remotion";

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** frame が start から dur かけて 0→1 */
export const ramp = (frame: number, start: number, dur = 12): number =>
  interpolate(frame, [start, start + dur], [0, 1], CLAMP);

/** 出現（透明度と下からの移動） */
export const appear = (
  frame: number,
  start: number,
  dur = 12,
  distance = 24,
): { opacity: number; transform: string } => {
  const t = ramp(frame, start, dur);
  return { opacity: t, transform: `translateY(${(1 - t) * distance}px)` };
};

export const pop = (frame: number, start: number, fps: number): number =>
  spring({ frame: frame - start, fps, config: { damping: 14, mass: 0.6 } });

export const lerp = (from: number, to: number, t: number): number =>
  from + (to - from) * t;

export { CLAMP };

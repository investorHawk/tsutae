import type { FootageId, Scene } from "../types";

export interface TimedScene {
  scene: Scene;
  index: number;
  from: number;
  durationInFrames: number;
}

/** 場面を累積フレームで並べる */
export const layoutScenes = (scenes: Scene[], fps: number): TimedScene[] => {
  let from = 0;
  return scenes.map((scene, index) => {
    const durationInFrames = Math.round(scene.seconds * fps);
    const timed = { scene, index, from, durationInFrames };
    from += durationInFrames;
    return timed;
  });
};

export const totalSeconds = (scenes: Scene[]): number =>
  scenes.reduce((sum, s) => sum + s.seconds, 0);

export const totalFrames = (scenes: Scene[], fps: number): number =>
  layoutScenes(scenes, fps).reduce((sum, t) => sum + t.durationInFrames, 0);

export interface FootageSegment {
  id: FootageId;
  fromSeconds: number;
  seconds: number;
}

/**
 * 場面の中で録画を出す区間。props.split が無ければ場面の秒数を均等に分ける。
 * kind "footage" では区間の合計が場面の秒数に等しい。masking（重ねる場面）は場面より短くてよい。
 */
export const footageSegments = (scene: Scene): FootageSegment[] => {
  const ids = scene.footage ?? [];
  if (ids.length === 0) return [];
  const split = scene.props?.split ?? ids.map(() => scene.seconds / ids.length);
  let fromSeconds = 0;
  return ids.map((id, i) => {
    const seconds = split[i] ?? 0;
    const seg = { id, fromSeconds, seconds };
    fromSeconds += seconds;
    return seg;
  });
};

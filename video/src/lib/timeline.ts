import type { FootageId, Scene, VoiceClip } from "../types";

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

export interface VoiceTimingOptions {
  /** 場面の頭から声が始まるまでの秒 */
  lead: number;
  /** 声が終わってから場面が終わるまでの秒 */
  tail: number;
  /** 場面 id ごとの下限の秒（アニメが潰れないように） */
  floors?: Record<string, number>;
}

export interface VoiceTimingResult {
  scenes: Scene[];
  /** 下限に当たった（声より長くした）場面の id */
  floored: string[];
}

/** 1/1000 秒に切り上げる（元の値を必ず下回らない） */
const ceilMs = (x: number): number => {
  const c = Math.ceil(x * 1000) / 1000;
  return c < x ? c + 0.001 : c;
};

const roundMs = (x: number): number => Math.round(x * 1000) / 1000;

/** split を合計が seconds になるよう比率で縮める（最後の区間で端数を吸収） */
const rescaleSplit = (split: number[], seconds: number): number[] => {
  const sum = split.reduce((a, b) => a + b, 0);
  if (split.length === 0 || sum <= 0) return [...split];
  const head = split.slice(0, -1).map((s) => roundMs((s * seconds) / sum));
  const rest = seconds - head.reduce((a, b) => a + b, 0);
  return [...head, roundMs(rest)];
};

const timeVoicedScene = (
  scene: Scene,
  clip: VoiceClip,
  opts: VoiceTimingOptions,
): { scene: Scene; floored: boolean } => {
  if (!Number.isFinite(clip.seconds) || clip.seconds < 0) {
    throw new Error(`声の秒が不正: ${clip.id} (${clip.seconds})`);
  }
  const wanted = ceilMs(opts.lead + clip.seconds + opts.tail);
  const floor = opts.floors?.[scene.id] ?? 0;
  const seconds = Math.max(wanted, floor);
  const split = scene.props?.split;
  const props = scene.props
    ? {
        ...scene.props,
        ...(split ? { split: rescaleSplit(split, seconds) } : {}),
      }
    : undefined;
  const voice = {
    file: clip.file,
    leadSeconds: opts.lead,
    seconds: clip.seconds,
  };
  return {
    scene: { ...scene, seconds, ...(props ? { props } : {}), voice },
    floored: floor > wanted,
  };
};

/**
 * 声の長さから場面の秒を決める（新しい場面の配列を返す。引数は変更しない）。
 * 声のある場面は lead + 声 + tail 秒（下限 floors を下回らない）、無い場面は元の秒。
 */
export const applyVoiceTiming = (
  scenes: Scene[],
  voice: VoiceClip[],
  opts: VoiceTimingOptions,
): VoiceTimingResult => {
  const byId = new Map(voice.map((c) => [c.id, c]));
  const results = scenes.map((scene) => {
    const clip = byId.get(scene.id);
    return clip
      ? timeVoicedScene(scene, clip, opts)
      : { scene: { ...scene }, floored: false };
  });
  return {
    scenes: results.map((r) => r.scene),
    floored: results.filter((r) => r.floored).map((r) => r.scene.id),
  };
};

// 場面ごとの声（先生が録った public/voice/b01.m4a など）を鳴らす時刻。React / remotion を import しない。
// 声の長さから尺を決めることはしない（場面の秒数は構成データのまま）。
import type { TimedScene } from "./timeline";

/** 場面の頭から声を鳴らし始めるまで（秒）。場面の切り替えのフェードと重ねない */
export const VOICE_OFFSET_SECONDS = 0.3;

export interface VoiceTrack {
  /** 声のキー（場面 id の頭。"b01"） */
  key: string;
  /** public からのパス（"voice/b01.m4a"） */
  src: string;
  /** 鳴らし始めるフレーム（動画の頭から） */
  from: number;
}

/** 場面 id の頭（最初の "-" より前）を小文字で。"b01-intro" → "b01" */
export const voiceKeyOf = (sceneId: string): string =>
  (sceneId.split("-")[0] ?? "").toLowerCase();

/** 声のある場面ごとに、鳴らすファイルと頭のフレームを返す */
export const voiceTracks = (
  timed: TimedScene[],
  voiceFiles: Record<string, string>,
  fps: number,
): VoiceTrack[] =>
  timed.flatMap(({ scene, from }) => {
    const key = voiceKeyOf(scene.id);
    const src = Object.hasOwn(voiceFiles, key) ? voiceFiles[key] : undefined;
    if (!src) return [];
    return [{ key, src, from: from + Math.round(VOICE_OFFSET_SECONDS * fps) }];
  });

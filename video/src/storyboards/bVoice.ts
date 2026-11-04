// 案 B に声をつけた版（DemoBVoice）。scripts/make_voice.py が書く src/voice.generated.json の
// 声の長さから場面の秒を決める。声が空なら scenesB の秒のまま（音なし）。
// STORYBOARDS には入れない（3 案は 150 秒固定のテストと文書の生成の対象なので）。
import { applyVoiceTiming, type VoiceTimingOptions } from "../lib/timeline";
import type { SceneKind, VoiceClip } from "../types";
import voiceJson from "../voice.generated.json";
import { scenesB, TITLE_B } from "./b";
import type { Storyboard } from "./index";

/** 元の秒に対する下限の割合（数字のアニメが潰れないように） */
const FLOOR_RATIO: Partial<Record<SceneKind, number>> = {
  coldopen: 0.875, // 8 秒 → 7 秒以上（3:00 → 0:30 の時計と「つたえ」）
  closing: 0.7, // 20 秒 → 14 秒以上（数字のカウントアップと Built with）
};

const floorsOf = (): Record<string, number> =>
  Object.fromEntries(
    scenesB.flatMap((s) => {
      const ratio = FLOOR_RATIO[s.kind];
      return ratio === undefined ? [] : [[s.id, s.seconds * ratio]];
    }),
  );

export const VOICE_TIMING_B: VoiceTimingOptions = {
  lead: 0.5,
  tail: 0.9,
  floors: floorsOf(),
};

/** 生成物の形を確かめて受け取る（壊れていれば bundle / テストの時点で落とす） */
const parseClips = (data: unknown): VoiceClip[] => {
  if (!Array.isArray(data)) {
    throw new Error("voice.generated.json は配列でない");
  }
  return data.map((row, i) => {
    const { id, file, seconds } = (row ?? {}) as Partial<VoiceClip>;
    if (typeof id !== "string" || typeof file !== "string") {
      throw new Error(`voice.generated.json の ${i} 行目に id / file が無い`);
    }
    if (typeof seconds !== "number") {
      throw new Error(`voice.generated.json の ${id} に seconds が無い`);
    }
    return { id, file, seconds };
  });
};

export const voiceClipsB: VoiceClip[] = parseClips(voiceJson);

const timed = applyVoiceTiming(scenesB, voiceClipsB, VOICE_TIMING_B);

export const demoBVoice: Storyboard & { floored: string[] } = {
  variant: "b",
  compositionId: "DemoBVoice",
  title: `${TITLE_B}（声つき）`,
  scenes: timed.scenes,
  bgm: true,
  floored: timed.floored,
};

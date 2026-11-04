// 生成物: scripts/footage-manifest.mjs が public/footage・public/audio・public/screens・public/voice/bgm.wav を走査して書く。
// 手で編集しない（npm run studio / render / still / bundle / test の前に自動で書き直される）。
import type { FootageId } from "./types";

export const footageFiles: Partial<Record<FootageId, string>> = {};

export const audioFiles: string[] = [];

/** 録画が無いときに出す静止画（public/screens/F<n>-<k>.png を k の順に） */
export const screenFiles: Partial<Record<FootageId, string[]>> = {
  F1: ["screens/F1-1.png", "screens/F1-2.png"],
  F2: ["screens/F2-1.png", "screens/F2-2.png", "screens/F2-3.png"],
  F4: ["screens/F4-1.png", "screens/F4-2.png"],
  F8: ["screens/F8-1.png", "screens/F8-2.png", "screens/F8-3.png"],
  F9: ["screens/F9-1.png"],
};

/** BGM（public/voice/bgm.wav。scripts/make_bgm.py が書く）。無ければ null */
export const bgmFile: string | null = "voice/bgm.wav";

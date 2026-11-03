// 生成物: scripts/footage-manifest.mjs が public/footage と public/audio を走査して書く。
// 手で編集しない（npm run studio / render / still / bundle / test の前に自動で書き直される）。
import type { FootageId } from "./types";

export const footageFiles: Partial<Record<FootageId, string>> = {};

export const audioFiles: string[] = [];

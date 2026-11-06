import type { Scene, Variant } from "../types";
import { scenesA, TITLE_A } from "./a";
import { scenesB, TITLE_B } from "./b";
import { scenesC, TITLE_C } from "./c";

export interface Storyboard {
  variant: Variant;
  compositionId: string;
  title: string;
  /** 狙いの尺（秒）。場面の秒数の合計はこれに等しい（テストで検査） */
  seconds: number;
  scenes: Scene[];
  /** BGM（public/audio/bgm.wav）を重ねるか。案 B だけ true */
  bgm?: boolean;
  /** 先生が narration を読み上げる案か（public/voice/ の声を置く。文書の見出しに使う）。案 B だけ true */
  voice?: boolean;
}

export const STORYBOARDS: Storyboard[] = [
  {
    variant: "a",
    compositionId: "DemoA",
    title: TITLE_A,
    seconds: 150,
    scenes: scenesA,
  },
  {
    variant: "b",
    compositionId: "DemoB",
    title: TITLE_B,
    seconds: 165,
    scenes: scenesB,
    bgm: true,
    voice: true,
  },
  {
    variant: "c",
    compositionId: "DemoC",
    title: TITLE_C,
    seconds: 150,
    scenes: scenesC,
  },
];

export { scenesA, scenesB, scenesC };

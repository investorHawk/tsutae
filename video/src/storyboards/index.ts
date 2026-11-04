import type { Scene, Variant } from "../types";
import { scenesA, TITLE_A } from "./a";
import { scenesB, TITLE_B } from "./b";
import { scenesC, TITLE_C } from "./c";

export interface Storyboard {
  variant: Variant;
  compositionId: string;
  title: string;
  scenes: Scene[];
  /** BGM（public/voice/bgm.wav）を重ねるか。DemoBVoice だけ true */
  bgm?: boolean;
}

export const STORYBOARDS: Storyboard[] = [
  { variant: "a", compositionId: "DemoA", title: TITLE_A, scenes: scenesA },
  { variant: "b", compositionId: "DemoB", title: TITLE_B, scenes: scenesB },
  { variant: "c", compositionId: "DemoC", title: TITLE_C, scenes: scenesC },
];

export { scenesA, scenesB, scenesC };

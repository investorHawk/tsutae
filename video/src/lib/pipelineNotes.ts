// pipeline の注記の置き場所。注記が 2 行以上なら図を上端を軸に縮め、図の下・字幕の帯の上に並べる。
// React / remotion を import しない。
import { SDK_FRAME } from "../scenes/pipelineLayout";
import { SUBTITLE_TOP } from "../theme";

/** 図の上端（SDK の枠のラベルの上）と下端（SDK の枠の下） */
const DIAGRAM_TOP = SDK_FRAME.y - 22;
const DIAGRAM_BOTTOM = SDK_FRAME.y + SDK_FRAME.h;
/** 注記の 1 行の高さ・行の間・図との間・字幕の帯との間（px） */
const NOTE_HEIGHT = 68;
const NOTE_GAP = 12;
const DIAGRAM_MARGIN = 14;
const SUBTITLE_MARGIN = 12;

export interface NotesLayout {
  /** 図の縮める割合（1 なら縮めない） */
  scale: number;
  /** 縮める軸（画面の px） */
  origin: { x: number; y: number };
  /** 各注記の上端（px） */
  tops: number[];
  /** 注記 1 行の高さ（px） */
  height: number;
}

export const notesLayout = (count: number): NotesLayout => {
  const n = Math.max(0, count);
  const block = n * NOTE_HEIGHT + Math.max(0, n - 1) * NOTE_GAP;
  const first = SUBTITLE_TOP - SUBTITLE_MARGIN - block;
  const room = first - DIAGRAM_MARGIN - DIAGRAM_TOP;
  const scale =
    n === 0 ? 1 : Math.min(1, room / (DIAGRAM_BOTTOM - DIAGRAM_TOP));
  return {
    scale,
    origin: { x: 960, y: DIAGRAM_TOP },
    tops: Array.from(
      { length: n },
      (_, i) => first + i * (NOTE_HEIGHT + NOTE_GAP),
    ),
    height: NOTE_HEIGHT,
  };
};

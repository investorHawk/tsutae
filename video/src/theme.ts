export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export const FONT_FAMILY =
  '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif';
export const MONO_FAMILY = '"SF Mono", Menlo, Consolas, monospace';

export const COLORS = {
  paper: "#f6f4ef",
  paperDeep: "#e9e5db",
  ink: "#1a1a1a",
  inkSoft: "#55524c",
  line: "#c9c3b6",
  navy: "#0b4a9c",
  purple: "#4b2a7b",
  reject: "#b3261e",
  accept: "#1b7f3b",
  highlight: "#f2b705",
  white: "#ffffff",
} as const;

export const FONT_SIZE = {
  body: 44,
  heading: 72,
  hero: 160,
  subtitle: 46,
  badge: 34,
} as const;

/** 字幕の帯の上端（これより下は字幕が重なる） */
export const SUBTITLE_TOP = 872;

/** 場面の切り替えのフェード（フレーム） */
export const FADE_FRAMES = 8;

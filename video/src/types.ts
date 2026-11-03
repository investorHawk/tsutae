// 構成データ（storyboards）の型。React / remotion を import しない（tsx・vitest が素で読む）。

export type SceneKind =
  | "title"
  | "coldopen"
  | "problem"
  | "before"
  | "after"
  | "footage"
  | "pipeline"
  | "masking"
  | "hookdemo"
  | "report"
  | "promises"
  | "closing";

export type FootageId =
  | "F1"
  | "F2"
  | "F3"
  | "F4"
  | "F5"
  | "F6"
  | "F7"
  | "F8"
  | "F9"
  | "F10";

export type Variant = "a" | "b" | "c";

export type ReportFocus = "alerts" | "timeline" | "symptoms" | "quotes";

export type HookId = "H1" | "H2" | "H3" | "H4";

export interface Bubble {
  who: "doctor" | "patient";
  text: string;
}

export interface Stat {
  label: string;
  /** clock: 秒数を m:ss で出す（from → to）。number: 0（または from）から to まで数える */
  format: "clock" | "number";
  from?: number;
  to: number;
  unit?: string;
}

export interface SceneProps {
  /** footage を複数出す場面の秒配分（footage と同じ長さ・同じ順） */
  split?: number[];
  /** report: 寄る領域の順 */
  focus?: ReportFocus[];
  /** pipeline: 1 つずつ点灯させる Hook（案 C） */
  hooks?: HookId[];
  /** pipeline: 背景に薄く敷く録画（任意。無くても成立） */
  backgroundFootage?: FootageId;
  /** pipeline: 図の下に出す注記 */
  notes?: string[];
  /** closing: カウントアップする数字 */
  stats?: Stat[];
  /** title / coldopen: タイトルの下の一文（行ごと） */
  lines?: string[];
  /** title: 小さな札 */
  tag?: string;
  /** problem / before: 吹き出し */
  bubbles?: Bubble[];
  /** before: 損失 */
  losses?: string[];
  /** after: 光らせる要確認の行（画像の行と同じ順） */
  alerts?: string[];
  /** footage: 右の帯に出す一言（split の区間ごと。null は出さない） */
  callouts?: (string | null)[];
  /** promises */
  dont?: string[];
  privacy?: string[];
}

export interface Scene {
  id: string;
  seconds: number;
  kind: SceneKind;
  /** 使う録画（順に出す）。複数なら props.split で秒配分 */
  footage?: FootageId[];
  /** 場面の見出し（画面に出す） */
  title?: string;
  /** 字幕（無ければ narration を字幕にする） */
  caption?: string;
  narration: string;
  /** storyboards.md の「画面に出すもの」（文書の生成用。描画には使わない） */
  screen?: string;
  props?: SceneProps;
}

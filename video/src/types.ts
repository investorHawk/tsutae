// 構成データ（storyboards）の型。React / remotion を import しない（tsx・vitest が素で読む）。

export type SceneKind =
  | "title"
  | "intro"
  | "coldopen"
  | "problem"
  | "before"
  | "after"
  | "notes"
  | "footage"
  | "pipeline"
  | "masking"
  | "hookdemo"
  | "report"
  | "promises"
  | "whypaper"
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
  | "F10"
  | "F11";

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

/** closing: 棒グラフの 1 行（秒に比例した長さの横棒と m:ss の時間） */
export interface CompareItem {
  label: string;
  seconds: number;
}

/** closing: 時間の棒グラフ（最後の行を紺で強調する） */
export interface Compare {
  title: string;
  items: CompareItem[];
}

/** closing: 棒グラフの下に出す事実（value を大きく） */
export interface Fact {
  label: string;
  value: string;
  note?: string;
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
  /** closing: カウントアップする数字（案 A・C） */
  stats?: Stat[];
  /** closing: 数字の札の代わりに出す時間の棒グラフ（案 B） */
  compare?: Compare;
  /** closing: 棒グラフの下に出す事実（compare と一緒に使う） */
  facts?: Fact[];
  /** closing: 最後のカードに出す文（1 つ目は大きく、2 つ目は最後に出す） */
  messages?: string[];
  /** intro: 経歴の札（順に出す） */
  career?: string[];
  /** intro: career のうち紺で強調する札 */
  careerFocus?: string;
  /** whypaper: 電子カルテを変える壁 */
  barriers?: string[];
  /** whypaper: 紙にして得られること */
  gains?: string[];
  /** title / coldopen / intro: タイトルの下の一文（行ごと） */
  lines?: string[];
  /** title: 小さな札 */
  tag?: string;
  /** problem / before: 吹き出し */
  bubbles?: Bubble[];
  /** before: 損失 */
  losses?: string[];
  /** before: 時計が回り切る秒（既定 180）。after: 時計に出す秒（既定 30） */
  clockSeconds?: number;
  /** after: 光らせる要確認の行（画像の行と同じ順） */
  alerts?: string[];
  /** notes: 書式の違うノートの札 */
  formatLabel?: string;
  /** notes: 患者と医師の負担の札（2 つ） */
  burdens?: string[];
  /** notes: 最後に紺で強調する文 */
  answer?: string;
  /** notes: answer の下に大きく出す名前 */
  brand?: string;
  /** footage: 右の帯に出す一言（split の区間ごと。null は出さない。区間より多ければ最後の区間を均等に割って順に出す） */
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
  /** 字幕の文。案 B では先生が読み上げる原稿でもある */
  narration: string;
  /** storyboards.md の「画面に出すもの」（文書の生成用。描画には使わない） */
  screen?: string;
  props?: SceneProps;
}

// pipeline の図の配置（README の mermaid を簡略化）。座標は 1920×1080 の px。
import type { HookId } from "../types";

export type NodeTone =
  | "mask"
  | "muted"
  | "hook"
  | "agent"
  | "role"
  | "tool"
  | "paper";

export interface PipeNode {
  id: string;
  label: string;
  sub?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  tone: NodeTone;
  hook?: HookId;
  /** props.hooks に入っているときだけ出す（H3・H4） */
  onlyWithHooks?: boolean;
}

export interface PipeEdge {
  from: string;
  to: string;
  /** 矢印の点（from の右端 → to の左端などを自前で指定） */
  points: [number, number][];
  tone?: "normal" | "reject" | "muted";
  label?: string;
  /** ラベルの位置（文字の中央下） */
  labelAt?: [number, number];
}

export const NODES: PipeNode[] = [
  {
    id: "mask",
    label: "伏せ字",
    sub: "二段（一次・二次）",
    x: 60,
    y: 260,
    w: 300,
    h: 130,
    tone: "mask",
  },
  {
    id: "leak",
    label: "疑いは送らない",
    sub: "院内画面だけ",
    x: 60,
    y: 470,
    w: 300,
    h: 110,
    tone: "muted",
  },
  {
    id: "H1",
    label: "H1",
    sub: "伏せ字漏れ",
    x: 420,
    y: 260,
    w: 200,
    h: 130,
    tone: "hook",
    hook: "H1",
  },
  {
    id: "main",
    label: "主エージェント",
    sub: "Skill を読む",
    x: 690,
    y: 250,
    w: 400,
    h: 150,
    tone: "agent",
  },
  {
    id: "date",
    label: "日付",
    sub: "date-normalizer",
    x: 1150,
    y: 195,
    w: 320,
    h: 96,
    tone: "role",
  },
  {
    id: "term",
    label: "用語",
    sub: "term-mapper",
    x: 1150,
    y: 305,
    w: 320,
    h: 96,
    tone: "role",
  },
  {
    id: "contra",
    label: "食い違い",
    sub: "contradiction-finder",
    x: 1150,
    y: 415,
    w: 320,
    h: 96,
    tone: "role",
  },
  {
    id: "emit",
    label: "emit_report",
    sub: "結果を受け取る",
    x: 690,
    y: 540,
    w: 400,
    h: 110,
    tone: "tool",
  },
  {
    id: "H2",
    label: "H2",
    sub: "引用は原文に？",
    x: 1150,
    y: 540,
    w: 250,
    h: 110,
    tone: "hook",
    hook: "H2",
  },
  { id: "a4", label: "A4", x: 1530, y: 470, w: 180, h: 234, tone: "paper" },
  {
    id: "H3",
    label: "H3",
    sub: "Skill の書き換え先",
    x: 60,
    y: 630,
    w: 300,
    h: 110,
    tone: "hook",
    hook: "H3",
    onlyWithHooks: true,
  },
  {
    id: "H4",
    label: "H4",
    sub: "許可外の道具",
    x: 1560,
    y: 290,
    w: 300,
    h: 110,
    tone: "hook",
    hook: "H4",
    onlyWithHooks: true,
  },
];

export const EDGES: PipeEdge[] = [
  {
    from: "mask",
    to: "leak",
    points: [
      [210, 390],
      [210, 470],
    ],
    tone: "muted",
  },
  {
    from: "mask",
    to: "H1",
    points: [
      [360, 325],
      [420, 325],
    ],
  },
  {
    from: "H1",
    to: "main",
    points: [
      [620, 325],
      [690, 325],
    ],
  },
  {
    from: "main",
    to: "date",
    points: [
      [1090, 300],
      [1150, 243],
    ],
  },
  {
    from: "main",
    to: "term",
    points: [
      [1090, 325],
      [1150, 353],
    ],
  },
  {
    from: "main",
    to: "contra",
    points: [
      [1090, 350],
      [1150, 463],
    ],
  },
  {
    from: "main",
    to: "emit",
    points: [
      [890, 400],
      [890, 540],
    ],
  },
  {
    from: "emit",
    to: "H2",
    points: [
      [1090, 595],
      [1150, 595],
    ],
  },
  {
    from: "H2",
    to: "a4",
    points: [
      [1400, 595],
      [1530, 595],
    ],
    tone: "normal",
    label: "受理",
    labelAt: [1446, 578],
  },
  {
    from: "H2",
    to: "main",
    points: [
      [1275, 650],
      [1275, 720],
      [640, 720],
      [640, 380],
      [690, 380],
    ],
    tone: "reject",
    label: "拒否と理由",
    labelAt: [960, 708],
  },
];

/** 図が組み上がる順（A・B は全体、C は前半で組み、後半で Hook を 1 つずつ点灯） */
export const BUILD_ORDER = [
  "mask",
  "leak",
  "H1",
  "main",
  "date",
  "term",
  "contra",
  "emit",
  "H2",
  "a4",
  "reject",
  "H3",
  "H4",
] as const;

export const HOOK_TEXT: Record<HookId, string> = {
  H1: "H1 送る直前に伏せ字漏れを検査",
  H2: "H2 引用が原文に無ければ拒否",
  H3: "H3 Skill の書き換え先を限る",
  H4: "H4 許可外の道具を止める",
};

/** Claude Agent SDK の枠 */
export const SDK_FRAME = { x: 625, y: 150, w: 875, h: 610 };

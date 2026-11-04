/**
 * D5 パイプライン可視化の組み立て（純関数）。API のイベントには文面が無い
 * （event 名・hook_name・agent_type・tool_name・decision・duration_ms だけ）。
 *
 * イベント名はバックエンドの実装に依らないよう、列から分類する:
 * - hook_name が H1〜H4（"H2" "h3_skill_path" 等）→ Hook
 * - tool_name / event が emit_timeline・emit_report → emit
 * - event 名に subagent を含む、または 3役の agent_type でツールなし → サブエージェント
 * - tool_name あり → ツール、それ以外 → 変換全体の出来事
 * レーンは agent_type が3役ならその役、それ以外は主エージェント。
 *
 * 題名（title）は医師・審査員が読む日本語の一行にし、内部のコード（event 名・
 * tool_name・役の名前）は codes に分けて小さく添える（D6-4）。
 */
import type { PipelineEvent, VisitStatus } from "../../api/types";

export const ROLES = [
  "date-normalizer",
  "term-mapper",
  "contradiction-finder",
] as const;
export type Role = (typeof ROLES)[number];
export type Lane = "main" | Role;
export const LANES: readonly Lane[] = ["main", ...ROLES];

export const HOOK_IDS = ["H1", "H2", "H3", "H4"] as const;
export type HookId = (typeof HOOK_IDS)[number];

export type EventKind = "hook" | "subagent" | "emit" | "tool" | "run";
export type Tone = "ok" | "deny" | "warn" | "neutral";
export type LaneState = "waiting" | "running" | "done" | "ended";

export const HOOK_LABELS: Readonly<Record<HookId, string>> = {
  H1: "送信前の伏せ字漏れ検査",
  H2: "引用と原文の照合",
  H3: "Skill の書き込み先の制限",
  H4: "許可外のツール・役の拒否",
};

/** レーンの題名（日本語）・内部名（code。主エージェントは空）・役目の説明。 */
export const LANE_LABELS: Readonly<
  Record<Lane, { title: string; code: string; description: string }>
> = {
  main: {
    title: "主エージェント（統合役）",
    code: "",
    description:
      "3人の担当を呼び、結果をまとめて時系列とレポートの項目を提出する",
  },
  "date-normalizer": {
    title: "日付の担当",
    code: "date-normalizer",
    description: "「昨日」「点滴の次の日」などを暦日・Day に直す",
  },
  "term-mapper": {
    title: "用語の担当",
    code: "term-mapper",
    description: "症状を CTCAE v5.0 JCOG版の用語名に当てはめる",
  },
  "contradiction-finder": {
    title: "食い違いの担当",
    code: "contradiction-finder",
    description: "質問への回答と自由記載の食い違いを、解決せずに並べる",
  },
};

const EMIT_TITLES: Readonly<Record<string, string>> = {
  emit_timeline: "時系列を提出",
  emit_report: "レポートの項目を提出",
};

/** ツール（tool_name）の名前（名詞の形）。知らないツールは「ツール「X」の実行」。 */
export const TOOL_LABELS: Readonly<Record<string, string>> = {
  Skill: "Skill（質問集・レポートの形式）の読み込み",
  Agent: "担当（サブエージェント）の呼び出し",
  mcp__tsutae__emit_timeline: "時系列の提出",
  mcp__tsutae__emit_report: "レポートの項目の提出",
};

/** 変換全体の出来事（ログの event 名）の見出し。知らない名前はそのまま出す。 */
export const RUN_TITLES: Readonly<Record<string, string>> = {
  input_prepared: "入力を準備（伏せ字・範囲）",
  run_start: "変換を開始",
  skill_check: "Skill の版を照合",
  run_end: "変換を終了",
  fallback: "AI変換なしに切り替え",
  internal_error: "想定外のエラー",
  config_error: "設定の誤り（Skill・モデルなど）",
  visit_ready: "レポートを作成",
  visit_failed: "レポートを作れなかった",
  visit_closed: "印刷済み・期限切れ（何もしない）",
  orphan_recovered: "再起動で止まった受診を回収",
  regenerate_requested: "医師が AI でもう一度変換を依頼",
  // 未処理の記載（D6）を医師が伏せ字にして変換し直す
  doctor_mask_saved: "医師が未処理の記載を伏せ字にして保存",
  doctor_mask_confirmed: "医師が「個人を特定する語は無い」と確かめた",
  doctor_mask_removed: "医師が伏せ字をやめた（未処理のまま）",
  doctor_masks_applied: "医師が伏せ字にした記録を入力に入れた",
  doctor_confirmed_sent: "人が確かめてから送った記録を入力に入れた",
};

/** Hook の出来事のうち、題名に一言を添えるもの（event 名 → 添える語）。 */
const HOOK_EVENT_TITLES: Readonly<Record<string, string>> = {
  hook_h1_confirmed: "医師が確かめた語だけを通した",
};

const DECISION_LABELS: ReadonlyArray<[RegExp, string, Tone]> = [
  [/^(deny|denied)\b/i, "拒否", "deny"],
  [/^block/i, "遮断", "deny"],
  [/^reject/i, "差し戻し", "deny"],
  [/^(allow|allowed|pass)\b/i, "許可", "ok"],
  [/^(accept|accepted|ok)\b/i, "受理", "ok"],
  [/^confirmed\b/i, "人が確認済み", "ok"],
  [/^sent\b/i, "送った記録", "neutral"],
  [/^entry\b/i, "記録", "neutral"],
];

const STOP_PATTERN = /(stop|end|done|finish|complete)/i;
const START_PATTERN = /start/i;
const WARN_PATTERN = /(fail|error|timeout|fallback|max_turns|max_budget)/i;

export interface ViewEvent {
  index: number;
  ts: string;
  elapsedMs: number | null;
  lane: Lane;
  kind: EventKind;
  hookId: HookId | null;
  /** 日本語の一行（内部のコードを混ぜない） */
  title: string;
  /** 小さく添える内部のコード（event 名・tool_name・役の名前）。題名と同じものは除く */
  codes: string[];
  tone: Tone;
  /** "拒否" "受理" など。decision が無ければ空 */
  decisionLabel: string;
  /** decision の ":" より後（規則名などのコード）。無ければ空 */
  decisionCode: string;
  source: PipelineEvent;
}

export interface LaneSummary {
  lane: Lane;
  title: string;
  /** 内部名（3役の agent_type）。主エージェントは空 */
  code: string;
  description: string;
  state: LaneState;
  events: ViewEvent[];
  /** events の件数 */
  count: number;
  /** 最後の出来事。無ければ null */
  last: ViewEvent | null;
  denied: number;
}

export interface HookSummary {
  hookId: HookId;
  label: string;
  fired: number;
  denied: number;
}

export interface RunSummary {
  count: number;
  denied: number;
  elapsedMs: number | null;
}

function isRole(value: string | null): value is Role {
  return value !== null && (ROLES as readonly string[]).includes(value);
}

function parseHookId(hookName: string | null): HookId | null {
  const match = hookName ? /^h([1-4])(?![0-9])/i.exec(hookName) : null;
  return match ? (`H${match[1]}` as HookId) : null;
}

function emitName(e: PipelineEvent): string | null {
  const names = Object.keys(EMIT_TITLES);
  const fromTool = names.find((n) => e.tool_name?.endsWith(`__${n}`));
  return fromTool ?? names.find((n) => e.event === n) ?? null;
}

function kindOf(e: PipelineEvent, hookId: HookId | null): EventKind {
  if (hookId) {
    return "hook";
  }
  if (emitName(e)) {
    return "emit";
  }
  if (/subagent/i.test(e.event) || (isRole(e.agent_type) && !e.tool_name)) {
    return "subagent";
  }
  return e.tool_name ? "tool" : "run";
}

function splitDecision(decision: string | null): [string, string, Tone] {
  if (!decision) {
    return ["", "", "neutral"];
  }
  const found = DECISION_LABELS.find(([pattern]) => pattern.test(decision));
  const colon = decision.indexOf(":");
  const code = colon >= 0 ? decision.slice(colon + 1) : "";
  return found ? [found[1], code, found[2]] : [decision, "", "neutral"];
}

function toolLabel(toolName: string): string {
  return TOOL_LABELS[toolName] ?? `ツール「${toolName}」の実行`;
}

function subagentTitle(e: PipelineEvent): string {
  const who = isRole(e.agent_type)
    ? LANE_LABELS[e.agent_type].title
    : "サブエージェント";
  if (STOP_PATTERN.test(e.event)) {
    return `${who}が作業を終了`;
  }
  return START_PATTERN.test(e.event) ? `${who}が作業を開始` : `${who}の出来事`;
}

function titleOf(e: PipelineEvent, kind: EventKind, hookId: HookId | null) {
  switch (kind) {
    case "hook": {
      const base = `${hookId} ${HOOK_LABELS[hookId as HookId]}`;
      const extra = HOOK_EVENT_TITLES[e.event];
      if (extra) {
        return `${base}：${extra}`;
      }
      return e.tool_name ? `${base}：${toolLabel(e.tool_name)}` : base;
    }
    case "emit":
      return EMIT_TITLES[emitName(e) as string];
    case "subagent":
      return subagentTitle(e);
    case "tool":
      return `${toolLabel(e.tool_name as string)}が終わった`;
    default:
      return RUN_TITLES[e.event] ?? e.event;
  }
}

/** 題名に添える内部のコード（event 名・tool_name・サブエージェントの役の名前）。 */
function codesOf(e: PipelineEvent, kind: EventKind, title: string): string[] {
  const role = kind === "subagent" ? e.agent_type : null;
  return [e.event, e.tool_name, role].filter(
    (c): c is string => c !== null && c !== "" && c !== title,
  );
}

function elapsedFrom(start: number, ts: string): number | null {
  const ms = Date.parse(ts);
  return Number.isNaN(start) || Number.isNaN(ms) ? null : ms - start;
}

export function toViewEvents(events: readonly PipelineEvent[]): ViewEvent[] {
  const start = events.length > 0 ? Date.parse(events[0].ts) : Number.NaN;
  return events.map((e, index) => {
    const hookId = parseHookId(e.hook_name);
    const kind = kindOf(e, hookId);
    const [decisionLabel, decisionCode, decisionTone] = splitDecision(
      e.decision,
    );
    const tone =
      decisionTone === "neutral" && WARN_PATTERN.test(e.event)
        ? "warn"
        : decisionTone;
    const title = titleOf(e, kind, hookId);
    return {
      index,
      ts: e.ts,
      elapsedMs: elapsedFrom(start, e.ts),
      lane: isRole(e.agent_type) ? e.agent_type : "main",
      kind,
      hookId,
      title,
      codes: codesOf(e, kind, title),
      tone,
      decisionLabel,
      decisionCode,
      source: e,
    };
  });
}

function laneState(
  lane: Lane,
  events: readonly ViewEvent[],
  finished: boolean,
): LaneState {
  if (events.length === 0) {
    return "waiting";
  }
  if (lane === "main") {
    return finished ? "done" : "running";
  }
  const stopped = events.some(
    (v) => v.kind === "subagent" && STOP_PATTERN.test(v.source.event),
  );
  if (stopped) {
    return "done";
  }
  return finished ? "ended" : "running";
}

export function laneSummaries(
  views: readonly ViewEvent[],
  finished: boolean,
): LaneSummary[] {
  return LANES.map((lane) => {
    const events = views.filter((v) => v.lane === lane);
    return {
      lane,
      ...LANE_LABELS[lane],
      state: laneState(lane, events, finished),
      events,
      count: events.length,
      last: events.length > 0 ? events[events.length - 1] : null,
      denied: events.filter((v) => v.tone === "deny").length,
    };
  });
}

export function hookSummaries(views: readonly ViewEvent[]): HookSummary[] {
  return HOOK_IDS.map((hookId) => {
    const fired = views.filter((v) => v.hookId === hookId);
    return {
      hookId,
      label: HOOK_LABELS[hookId],
      fired: fired.length,
      denied: fired.filter((v) => v.tone === "deny").length,
    };
  });
}

export function runSummary(views: readonly ViewEvent[]): RunSummary {
  const last = views.length > 0 ? views[views.length - 1].elapsedMs : null;
  return {
    count: views.length,
    denied: views.filter((v) => v.tone === "deny").length,
    elapsedMs: last,
  };
}

export interface LiveStatus {
  text: string;
  /** true なら更新中（点滅の印を付ける） */
  on: boolean;
}

/**
 * 画面上部の「更新中／止めました」。受診の状態（最後に取れたもの。無ければ null）と、
 * ポーリングが止まったかから決める。変換が終わった状態を見たら、最後の1回の取り直し
 * （遅れて記録される出来事を拾う）を待たずに止めた表示にする（D6-2）。
 */
export function liveStatus(
  status: VisitStatus | null,
  stopped: boolean,
): LiveStatus {
  if (status === "ready" || status === "printed") {
    return { text: "更新を止めました（完了）", on: false };
  }
  if (status === "failed") {
    return { text: "更新を止めました（失敗で終了）", on: false };
  }
  return stopped
    ? { text: "更新を止めました", on: false }
    : { text: "2秒ごとに更新中", on: true };
}

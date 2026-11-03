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
 */
import type { PipelineEvent } from "../../api/types";

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

export const LANE_LABELS: Readonly<
  Record<Lane, { title: string; description: string }>
> = {
  main: {
    title: "主エージェント（統合役）",
    description: "3役を呼び、emit_timeline / emit_report を出す",
  },
  "date-normalizer": {
    title: "date-normalizer",
    description: "相対時間の表現を暦日・Day に直す",
  },
  "term-mapper": {
    title: "term-mapper",
    description: "症状を CTCAE v5.0 JCOG版の用語名に当てはめる",
  },
  "contradiction-finder": {
    title: "contradiction-finder",
    description: "クローズ回答と自由記載の食い違いを解決せずに並べる",
  },
};

const EMIT_TITLES: Readonly<Record<string, string>> = {
  emit_timeline: "emit_timeline 時系列を提出",
  emit_report: "emit_report レポートの項目を提出",
};

/** 変換全体の出来事（ログの event 名）の見出し。知らない名前はそのまま出す。 */
export const RUN_TITLES: Readonly<Record<string, string>> = {
  input_prepared: "input_prepared 入力を準備（伏せ字・範囲）",
  run_start: "run_start 変換を開始",
  skill_check: "skill_check Skill の版を照合",
  run_end: "run_end 変換を終了",
  fallback: "fallback AI変換なしに切り替え",
  internal_error: "internal_error 想定外のエラー",
  config_error: "config_error 設定の誤り（Skill・モデルなど）",
  visit_ready: "visit_ready レポートを作成",
  visit_failed: "visit_failed レポートを作れなかった",
  visit_closed: "visit_closed 印刷済み・期限切れ（何もしない）",
  orphan_recovered: "orphan_recovered 再起動で止まった受診を回収",
};

const DECISION_LABELS: ReadonlyArray<[RegExp, string, Tone]> = [
  [/^(deny|denied)\b/i, "拒否", "deny"],
  [/^block/i, "遮断", "deny"],
  [/^reject/i, "差し戻し", "deny"],
  [/^(allow|allowed|pass)\b/i, "許可", "ok"],
  [/^(accept|accepted|ok)\b/i, "受理", "ok"],
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
  title: string;
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
  description: string;
  state: LaneState;
  events: ViewEvent[];
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

function titleOf(e: PipelineEvent, kind: EventKind, hookId: HookId | null) {
  switch (kind) {
    case "hook":
      return `${hookId} ${HOOK_LABELS[hookId as HookId]}`;
    case "emit":
      return EMIT_TITLES[emitName(e) as string];
    case "subagent": {
      const who = e.agent_type ?? "サブエージェント";
      if (STOP_PATTERN.test(e.event)) {
        return `${who} 完了`;
      }
      return START_PATTERN.test(e.event) ? `${who} 開始` : `${who} ${e.event}`;
    }
    case "tool":
      return `ツール ${e.tool_name}`;
    default:
      return RUN_TITLES[e.event] ?? e.event;
  }
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
    return {
      index,
      ts: e.ts,
      elapsedMs: elapsedFrom(start, e.ts),
      lane: isRole(e.agent_type) ? e.agent_type : "main",
      kind,
      hookId,
      title: titleOf(e, kind, hookId),
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

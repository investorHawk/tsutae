import { describe, expect, it } from "vitest";
import type { PipelineEvent } from "../../api/types";
import {
  hookSummaries,
  laneSummaries,
  runSummary,
  toViewEvents,
} from "./pipelineEvents";

function ev(patch: Partial<PipelineEvent>): PipelineEvent {
  return {
    ts: "2026-11-09T10:00:00+09:00",
    event: "run_start",
    hook_name: null,
    agent_type: null,
    tool_name: null,
    decision: null,
    duration_ms: null,
    ...patch,
  };
}

const EVENTS: PipelineEvent[] = [
  ev({ event: "run_start" }),
  ev({
    ts: "2026-11-09T10:00:00.500+09:00",
    event: "hook",
    hook_name: "H1",
    decision: "allow",
  }),
  ev({
    ts: "2026-11-09T10:00:02+09:00",
    event: "subagent_start",
    agent_type: "date-normalizer",
  }),
  ev({
    ts: "2026-11-09T10:00:03+09:00",
    event: "hook",
    hook_name: "H4",
    agent_type: "term-mapper",
    tool_name: "Bash",
    decision: "deny:not_allowed",
  }),
  ev({
    ts: "2026-11-09T10:00:09+09:00",
    event: "subagent_stop",
    agent_type: "date-normalizer",
    duration_ms: 7000,
  }),
  ev({
    ts: "2026-11-09T10:00:10+09:00",
    event: "hook",
    hook_name: "H2",
    tool_name: "mcp__tsutae__emit_timeline",
    decision: "deny:events.2.source_quote",
  }),
  ev({
    ts: "2026-11-09T10:00:11+09:00",
    event: "emit_timeline",
    tool_name: "mcp__tsutae__emit_timeline",
    decision: "accept",
  }),
  ev({
    ts: "2026-11-09T10:00:12+09:00",
    event: "post_tool_use",
    tool_name: "Agent",
  }),
];

describe("toViewEvents", () => {
  const views = toViewEvents(EVENTS);

  it("並びはそのまま、経過時間は最初の出来事から", () => {
    expect(views.map((v) => v.index)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(views[0].elapsedMs).toBe(0);
    expect(views[1].elapsedMs).toBe(500);
    expect(views[6].elapsedMs).toBe(11_000);
  });

  it("3役の agent_type はそのレーン、それ以外は主エージェント", () => {
    expect(views.map((v) => v.lane)).toEqual([
      "main",
      "main",
      "date-normalizer",
      "term-mapper",
      "date-normalizer",
      "main",
      "main",
      "main",
    ]);
  });

  it("Hook・サブエージェント・emit・ツール・その他に分ける", () => {
    expect(views.map((v) => v.kind)).toEqual([
      "run",
      "hook",
      "subagent",
      "hook",
      "subagent",
      "hook",
      "emit",
      "tool",
    ]);
    expect(views[3].hookId).toBe("H4");
    expect(views[5].hookId).toBe("H2");
  });

  it("decision から色の区別（拒否・受理）を決める", () => {
    expect(views[1].tone).toBe("ok");
    expect(views[3].tone).toBe("deny");
    expect(views[5].tone).toBe("deny");
    expect(views[6].tone).toBe("ok");
    expect(views[0].tone).toBe("neutral");
  });

  it("題名は日本語の説明つき", () => {
    expect(views[1].title).toBe("H1 送信前の伏せ字漏れ検査");
    expect(views[2].title).toBe("date-normalizer 開始");
    expect(views[4].title).toBe("date-normalizer 完了");
    expect(views[6].title).toBe("emit_timeline 時系列を提出");
    expect(views[7].title).toBe("ツール Agent");
    expect(views[0].title).toBe("run_start");
  });

  it("decision は 拒否 / 受理 などの語とコードに分ける", () => {
    expect(views[5].decisionLabel).toBe("拒否");
    expect(views[5].decisionCode).toBe("events.2.source_quote");
    expect(views[6].decisionLabel).toBe("受理");
    expect(views[6].decisionCode).toBe("");
    expect(views[0].decisionLabel).toBe("");
  });

  it("小文字や接尾辞つきの hook_name も H1〜H4 として読む", () => {
    const [view] = toViewEvents([ev({ hook_name: "h3_skill_path" })]);
    expect(view.kind).toBe("hook");
    expect(view.hookId).toBe("H3");
  });

  it("H1〜H4 でない hook_name は Hook として数えない", () => {
    const [view] = toViewEvents([
      ev({ event: "subagent_start", hook_name: "SubagentStart" }),
    ]);
    expect(view.kind).toBe("subagent");
    expect(view.hookId).toBeNull();
  });

  it("失敗・フォールバックの出来事は注意の色", () => {
    const [a, b] = toViewEvents([
      ev({ event: "fallback" }),
      ev({ event: "sdk_error" }),
    ]);
    expect(a.tone).toBe("warn");
    expect(b.tone).toBe("warn");
  });

  it("ts が読めなければ経過時間は null", () => {
    const [view] = toViewEvents([ev({ ts: "bad" })]);
    expect(view.elapsedMs).toBeNull();
  });

  it("引数の配列を書き換えない", () => {
    const frozen = Object.freeze(EVENTS.map((e) => Object.freeze({ ...e })));
    expect(() => toViewEvents(frozen)).not.toThrow();
  });
});

describe("laneSummaries", () => {
  const views = toViewEvents(EVENTS);

  it("主エージェント＋3役の4レーンを順に返す", () => {
    expect(laneSummaries(views, false).map((l) => l.lane)).toEqual([
      "main",
      "date-normalizer",
      "term-mapper",
      "contradiction-finder",
    ]);
  });

  it("状態: 出来事なし=待機、stop あり=完了、それ以外=実行中", () => {
    const lanes = laneSummaries(views, false);
    expect(lanes.map((l) => l.state)).toEqual([
      "running",
      "done",
      "running",
      "waiting",
    ]);
  });

  it("変換が終わったら stop の無いレーンは「終了」、主エージェントは完了", () => {
    const lanes = laneSummaries(views, true);
    expect(lanes.map((l) => l.state)).toEqual([
      "done",
      "done",
      "ended",
      "waiting",
    ]);
  });

  it("レーンごとの出来事と拒否の数", () => {
    const lanes = laneSummaries(views, false);
    expect(lanes[1].events).toHaveLength(2);
    expect(lanes[2].denied).toBe(1);
  });
});

describe("hookSummaries", () => {
  it("H1〜H4 ごとの発火数と拒否数", () => {
    const hooks = hookSummaries(toViewEvents(EVENTS));
    expect(
      hooks.map(({ hookId, fired, denied }) => [hookId, fired, denied]),
    ).toEqual([
      ["H1", 1, 0],
      ["H2", 1, 1],
      ["H3", 0, 0],
      ["H4", 1, 1],
    ]);
  });
});

describe("runSummary", () => {
  it("出来事の数・拒否の数・最初から最後までの時間", () => {
    expect(runSummary(toViewEvents(EVENTS))).toEqual({
      count: 8,
      denied: 2,
      elapsedMs: 12_000,
    });
  });

  it("出来事が無ければ 0 件・時間 null", () => {
    expect(runSummary([])).toEqual({ count: 0, denied: 0, elapsedMs: null });
  });
});

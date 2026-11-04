import { describe, expect, it } from "vitest";
import type { PipelineEvent } from "../../api/types";
import {
  hookSummaries,
  laneSummaries,
  liveStatus,
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

  // D6-4: 題名は日本語の一行。内部のコード（event 名・tool_name）は codes に分けて小さく添える
  it("題名は日本語の一行（内部のコードを混ぜない）", () => {
    expect(views[0].title).toBe("変換を開始");
    expect(views[1].title).toBe("H1 送信前の伏せ字漏れ検査");
    expect(views[2].title).toBe("日付の担当が作業を開始");
    expect(views[3].title).toBe(
      "H4 許可外のツール・役の拒否：ツール「Bash」の実行",
    );
    expect(views[4].title).toBe("日付の担当が作業を終了");
    expect(views[5].title).toBe("H2 引用と原文の照合：時系列の提出");
    expect(views[6].title).toBe("時系列を提出");
    expect(views[7].title).toBe("担当（サブエージェント）の呼び出しが終わった");
    for (const v of views) {
      expect(v.title).not.toMatch(/mcp__|_start|_stop|run_|emit_/);
    }
  });

  it("内部のコード（event 名・tool_name）は codes に入る", () => {
    expect(views[0].codes).toEqual(["run_start"]);
    expect(views[5].codes).toEqual(["hook", "mcp__tsutae__emit_timeline"]);
    expect(views[6].codes).toEqual([
      "emit_timeline",
      "mcp__tsutae__emit_timeline",
    ]);
    expect(views[7].codes).toEqual(["post_tool_use", "Agent"]);
  });

  it("実際のログの Hook・ツールの名前も日本語にする", () => {
    const [h4, skill, h2, report] = toViewEvents([
      ev({ event: "hook_h4_allow", hook_name: "H4", tool_name: "Agent" }),
      ev({ event: "tool_use", tool_name: "Skill" }),
      ev({
        event: "hook_h2_allow",
        hook_name: "H2",
        tool_name: "mcp__tsutae__emit_report",
      }),
      ev({
        event: "emit_report",
        tool_name: "mcp__tsutae__emit_report",
        decision: "accept",
      }),
    ]);
    expect(h4.title).toBe(
      "H4 許可外のツール・役の拒否：担当（サブエージェント）の呼び出し",
    );
    expect(h4.codes).toEqual(["hook_h4_allow", "Agent"]);
    expect(skill.title).toBe(
      "Skill（質問集・レポートの形式）の読み込みが終わった",
    );
    expect(h2.title).toBe("H2 引用と原文の照合：レポートの項目の提出");
    expect(report.title).toBe("レポートの項目を提出");
  });

  it("医師が伏せ字にして・確かめて送ったことを日本語の一行で出す", () => {
    const [saved, confirmed, applied, sent, h1] = toViewEvents([
      ev({ event: "doctor_mask_saved", decision: "entry:38" }),
      ev({ event: "doctor_mask_confirmed", decision: "entry:38" }),
      ev({ event: "doctor_masks_applied", decision: "sent:1" }),
      ev({ event: "doctor_confirmed_sent", decision: "sent:1" }),
      ev({
        event: "hook_h1_confirmed",
        hook_name: "H1",
        decision: "confirmed:1",
      }),
    ]);
    expect(saved.title).toBe("医師が未処理の記載を伏せ字にして保存");
    expect([saved.decisionLabel, saved.decisionCode]).toEqual(["記録", "38"]);
    expect(confirmed.title).toBe("医師が「個人を特定する語は無い」と確かめた");
    expect(applied.title).toBe("医師が伏せ字にした記録を入力に入れた");
    expect(sent.title).toBe("人が確かめてから送った記録を入力に入れた");
    expect([sent.decisionLabel, sent.decisionCode]).toEqual([
      "送った記録",
      "1",
    ]);
    expect(h1.kind).toBe("hook");
    expect(h1.title).toBe(
      "H1 送信前の伏せ字漏れ検査：医師が確かめた語だけを通した",
    );
    expect([h1.decisionLabel, h1.tone]).toEqual(["人が確認済み", "ok"]);
  });

  it("知らない出来事の名前はそのまま出す（同じコードを二重に添えない）", () => {
    const [view] = toViewEvents([ev({ event: "something_new" })]);
    expect(view.title).toBe("something_new");
    expect(view.codes).toEqual([]);
  });

  it("知らない役の出来事は「サブエージェント」として出す", () => {
    const [view] = toViewEvents([
      ev({ event: "subagent_start", agent_type: "other-role" }),
    ]);
    expect(view.title).toBe("サブエージェントが作業を開始");
    expect(view.codes).toEqual(["subagent_start", "other-role"]);
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

  // D6-3: レーンは役ごとの要約（件数・最後の出来事・状態）。出来事を並べ直さない
  it("レーンの件数と最後の出来事（出来事が無ければ null）", () => {
    const lanes = laneSummaries(views, false);
    expect(lanes.map((l) => l.count)).toEqual([5, 2, 1, 0]);
    expect(lanes[1].last?.title).toBe("日付の担当が作業を終了");
    expect(lanes[0].last?.index).toBe(7);
    expect(lanes[3].last).toBeNull();
  });

  it("3役のレーンの題名は日本語、内部名は code に残す", () => {
    const lanes = laneSummaries(views, false);
    expect(lanes.map((l) => l.title)).toEqual([
      "主エージェント（統合役）",
      "日付の担当",
      "用語の担当",
      "食い違いの担当",
    ]);
    expect(lanes.map((l) => l.code)).toEqual([
      "",
      "date-normalizer",
      "term-mapper",
      "contradiction-finder",
    ]);
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

// D6-2: 変換が終わった（ready・printed・failed）のを見たら、最後の取り直しを待たずに
// 「止めました」と出す（取り直しの1回は遅れて記録される出来事のために裏で続ける）
describe("liveStatus", () => {
  it("まだ取れていない・変換中なら更新中", () => {
    expect(liveStatus(null, false)).toEqual({
      text: "2秒ごとに更新中",
      on: true,
    });
    expect(liveStatus("generating", false)).toEqual({
      text: "2秒ごとに更新中",
      on: true,
    });
  });

  it.each([
    ["ready", "更新を止めました（完了）"],
    ["printed", "更新を止めました（完了）"],
    ["failed", "更新を止めました（失敗で終了）"],
  ] as const)("%s なら止めた表示（取り直し中でも）", (status, text) => {
    expect(liveStatus(status, false)).toEqual({ text, on: false });
    expect(liveStatus(status, true)).toEqual({ text, on: false });
  });

  it("失敗（401・404）で止まったら、理由を付けずに止めた表示", () => {
    expect(liveStatus(null, true)).toEqual({
      text: "更新を止めました",
      on: false,
    });
    expect(liveStatus("generating", true)).toEqual({
      text: "更新を止めました",
      on: false,
    });
  });
});

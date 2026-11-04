/**
 * D5 の組み立てを、実際の API のイベント（fixture doctor_pipeline_events。
 * デモ患者を FakeRunner で変換したログ）に掛ける。イベント名を決め打ちしていないことの確認。
 */
import { describe, expect, it } from "vitest";
import type { PipelineEventsResponse } from "../../api/types";
import { fixtureBody } from "../../test/apiFixtures";
import {
  hookSummaries,
  laneSummaries,
  runSummary,
  toViewEvents,
} from "./pipelineEvents";

const BODY = fixtureBody("doctor_pipeline_events") as PipelineEventsResponse;
const VIEWS = toViewEvents(BODY.events);

describe("実際のイベント（ready の受診）", () => {
  it("全件を並べ、拒否は無い", () => {
    expect(BODY.status).toBe("ready");
    expect(runSummary(VIEWS)).toMatchObject({
      count: BODY.events.length,
      denied: 0,
    });
  });

  it("3役のレーンはそれぞれ開始・終了があり done", () => {
    const lanes = laneSummaries(VIEWS, true);
    for (const lane of lanes) {
      expect(lane.state).toBe("done");
      expect(lane.events.length).toBeGreaterThan(0);
    }
    const roles = lanes.filter((l) => l.lane !== "main");
    expect(roles.map((l) => l.events.map((v) => v.kind))).toEqual([
      ["subagent", "subagent"],
      ["subagent", "subagent"],
      ["subagent", "subagent"],
    ]);
  });

  it("Hook ごとの発火数（H1 は依頼文に1回、H2 は emit の2回、H3 は変換では使わない）", () => {
    const hooks = Object.fromEntries(
      hookSummaries(VIEWS).map((h) => [h.hookId, h]),
    );
    expect(hooks.H1.fired).toBe(1);
    expect(hooks.H2.fired).toBe(2);
    expect(hooks.H3.fired).toBe(0);
    expect(hooks.H4.fired).toBeGreaterThan(0);
    expect(Object.values(hooks).every((h) => h.denied === 0)).toBe(true);
  });

  it("題名は日本語の一行で、内部のコード（hook_h4_allow・mcp__ 等）は codes にだけある", () => {
    for (const v of VIEWS) {
      expect(v.title).toMatch(/[ぁ-んァ-ヶ一-龠]/);
      expect(v.title).not.toMatch(/mcp__|hook_h\d|tool_use|subagent_|_ready/);
      expect(v.codes).toContain(v.source.event);
    }
  });

  it("emit_timeline・emit_report の受理は emit として出る", () => {
    const emits = VIEWS.filter(
      (v) => v.kind === "emit" && v.decisionLabel === "受理",
    );
    expect(emits.map((v) => v.source.event)).toEqual([
      "emit_timeline",
      "emit_report",
    ]);
  });
});

describe("実際のイベント（生成中・印刷済み）", () => {
  it("生成中でまだログが無ければ空", () => {
    const body = fixtureBody(
      "doctor_pipeline_events_generating",
    ) as PipelineEventsResponse;
    expect(body.status).toBe("generating");
    expect(toViewEvents(body.events)).toEqual([]);
  });

  it("印刷済みでもログは残る（状態は printed）", () => {
    const body = fixtureBody(
      "doctor_pipeline_events_printed",
    ) as PipelineEventsResponse;
    expect(body.status).toBe("printed");
    expect(body.events).toEqual(BODY.events);
  });
});

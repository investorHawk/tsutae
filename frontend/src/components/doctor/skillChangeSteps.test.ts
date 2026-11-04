import { describe, expect, it } from "vitest";
import { skillChangeSteps, type StepState } from "./skillChangeSteps";
import type { SkillPhase } from "./useSkillChangeFlow";

const TARGET = {
  id: 5,
  skillName: "regimen-folfox",
  requestText: "（合成）",
  diff: "-a\n+b\n",
};

function states(phase: SkillPhase): StepState[] {
  return skillChangeSteps(phase).map((s) => s.state);
}

// D5-3: 「依頼 → 差分を見る → 承認」のどこにいるかを、流れの段階から決める
describe("skillChangeSteps", () => {
  it("3段階の名前", () => {
    expect(skillChangeSteps({ kind: "input" }).map((s) => s.label)).toEqual([
      "依頼を書く",
      "差分を見る",
      "承認して反映",
    ]);
  });

  it("入力中は 1 が今", () => {
    expect(states({ kind: "input" })).toEqual(["current", "todo", "todo"]);
  });

  it("生成中は 1 が済み、2 が今（差分を作っている）", () => {
    const steps = skillChangeSteps({
      kind: "generating",
      skillName: "regimen-folfox",
      startedAt: 0,
      changeId: null,
    });
    expect(steps.map((s) => s.state)).toEqual(["done", "current", "todo"]);
    expect(steps[1].note).toBe("Claude が差分を作成中");
  });

  it("差分の確認中は 2 が今（承認か却下を選ぶ）", () => {
    const steps = skillChangeSteps({
      kind: "review",
      target: TARGET,
      busy: false,
      error: null,
    });
    expect(steps.map((s) => s.state)).toEqual(["done", "current", "todo"]);
    expect(steps[1].note).toBe("差分を見て、承認か却下を選ぶ");
  });

  it("承認したら全て済み（新しい版）", () => {
    const steps = skillChangeSteps({
      kind: "approved",
      skillName: "regimen-folfox",
      newVersion: 2,
    });
    expect(steps.map((s) => s.state)).toEqual(["done", "done", "done"]);
    expect(steps[2].note).toBe("第2版になりました");
  });

  it("却下したら 3 は止まる（反映しない）", () => {
    const steps = skillChangeSteps({
      kind: "rejected",
      skillName: "regimen-folfox",
    });
    expect(steps.map((s) => s.state)).toEqual(["done", "done", "stopped"]);
    expect(steps[2].note).toBe("却下（反映しない）");
  });

  it("書き換えに失敗したら 2 で止まる", () => {
    const steps = skillChangeSteps({
      kind: "failed",
      changeId: 5,
      code: "no_change",
    });
    expect(steps.map((s) => s.state)).toEqual(["done", "stopped", "todo"]);
    expect(steps[1].note).toBe("差分を作れませんでした");
  });
});

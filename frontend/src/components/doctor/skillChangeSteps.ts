/**
 * D4 の「依頼 → 差分を見る → 承認」の段階の表示（純関数。D5-3）。
 * useSkillChangeFlow の段階（SkillPhase）から、どこまで済み・今どこかを決める。
 */
import { versionLabel } from "./skillLabels";
import type { SkillPhase } from "./useSkillChangeFlow";

export type StepState = "done" | "current" | "todo" | "stopped";

export interface Step {
  label: string;
  state: StepState;
  /** その段階の一言（無ければ空） */
  note: string;
}

const LABELS = ["依頼を書く", "差分を見る", "承認して反映"] as const;

type Plan = readonly [StepState, StepState, StepState];

function planOf(phase: SkillPhase): [Plan, string[]] {
  switch (phase.kind) {
    case "generating":
      return [
        ["done", "current", "todo"],
        ["", "Claude が差分を作成中", ""],
      ];
    case "review":
      return [
        ["done", "current", "todo"],
        ["", "差分を見て、承認か却下を選ぶ", ""],
      ];
    case "approved":
      return [
        ["done", "done", "done"],
        ["", "", `${versionLabel(phase.newVersion)}になりました`],
      ];
    case "rejected":
      return [
        ["done", "done", "stopped"],
        ["", "", "却下（反映しない）"],
      ];
    case "failed":
      return [
        ["done", "stopped", "todo"],
        ["", "差分を作れませんでした", ""],
      ];
    default:
      return [
        ["current", "todo", "todo"],
        ["", "", ""],
      ];
  }
}

export function skillChangeSteps(phase: SkillPhase): Step[] {
  const [states, notes] = planOf(phase);
  return LABELS.map((label, i) => ({
    label,
    state: states[i],
    note: notes[i],
  }));
}

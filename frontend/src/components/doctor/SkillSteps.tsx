import { skillChangeSteps, type StepState } from "./skillChangeSteps";
import type { SkillPhase } from "./useSkillChangeFlow";

const STATE_LABELS: Readonly<Record<StepState, string>> = {
  done: "済み",
  current: "今ここ",
  todo: "",
  stopped: "止まりました",
};

/** D4 の「依頼を書く → 差分を見る → 承認して反映」。今の段階に aria-current。 */
export default function SkillSteps({ phase }: { phase: SkillPhase }) {
  return (
    <ol className="d-steps" aria-label="手順">
      {skillChangeSteps(phase).map((step, i) => (
        <li
          key={step.label}
          className={`d-step d-step--${step.state}`}
          aria-current={step.state === "current" ? "step" : undefined}
        >
          <span className="d-step-no" aria-hidden="true">
            {i + 1}
          </span>
          <span className="d-step-label">{step.label}</span>
          {STATE_LABELS[step.state] ? (
            <span className="d-step-state">{STATE_LABELS[step.state]}</span>
          ) : null}
          {step.note ? <span className="d-step-note">{step.note}</span> : null}
        </li>
      ))}
    </ol>
  );
}

import type { FormEvent, ReactNode } from "react";
import type { SkillInfo } from "../../api/types";
import { skillOptionLabel } from "./skillLabels";

export const EXAMPLE_REQUEST = "口内炎は、食事がとれたかも次から聞いて";
export const REQUEST_MAX_LENGTH = 300;

interface SkillRequestFormProps {
  skills: readonly SkillInfo[];
  skillName: string;
  requestText: string;
  locked: boolean;
  onSkillChange: (name: string) => void;
  onTextChange: (text: string) => void;
  onSubmit: () => void;
  /** Skill の選択の下（依頼の一文の前）に置くもの。今の中身（SkillContentPanel） */
  preview?: ReactNode;
}

/** D4 の入力。Skill を選び（呼び名と版。内部名は小さく添える）、変えたいことを一文で書く。 */
export default function SkillRequestForm({
  skills,
  skillName,
  requestText,
  locked,
  onSkillChange,
  onTextChange,
  onSubmit,
  preview = null,
}: SkillRequestFormProps) {
  const canSubmit = !locked && skillName !== "" && requestText.trim() !== "";

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (canSubmit) {
      onSubmit();
    }
  }

  return (
    <form className="d-skill-form" onSubmit={handleSubmit}>
      <label className="d-field">
        <span>Skill</span>
        <select
          value={skillName}
          disabled={locked}
          onChange={(e) => onSkillChange(e.target.value)}
        >
          {skills.map((skill) => (
            <option key={skill.name} value={skill.name}>
              {skillOptionLabel(skill)}
            </option>
          ))}
        </select>
      </label>
      {skillName ? (
        <p className="d-skill-name">
          内部名 <code className="d-skill-code">{skillName}</code>
        </p>
      ) : null}
      {preview}
      <label className="d-field">
        <span>変えたいこと（一文）</span>
        <textarea
          value={requestText}
          maxLength={REQUEST_MAX_LENGTH}
          placeholder={`例: ${EXAMPLE_REQUEST}`}
          disabled={locked}
          onChange={(e) => onTextChange(e.target.value)}
        />
      </label>
      <div className="d-actions">
        <button type="submit" className="d-primary" disabled={!canSubmit}>
          書き換えを依頼する
        </button>
        <button
          type="button"
          disabled={locked}
          onClick={() => onTextChange(EXAMPLE_REQUEST)}
        >
          例を入れる
        </button>
      </div>
    </form>
  );
}

import type { ReactNode } from "react";
import { aiCountIn, sectionErrors, sectionIssues } from "./fieldState";
import { sectionDomId } from "./fieldLabels";
import { useRegimenForm } from "./formContext";

interface FormSectionProps {
  section: string;
  title: string;
  /** 見出しの右（行を足すボタンなど） */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * フォームの節。Claude が節ごと聞いているときは赤枠と札、節の単位の欠け（「薬を1剤以上」
 * 「Day1 に点滴」など）はピンクの箱で出す。見出しは札から飛べるように focus できる。
 */
export default function FormSection({
  section,
  title,
  actions,
  children,
}: FormSectionProps) {
  const { draft, ask, fieldErrors } = useRegimenForm();
  const asked = ask?.field_id === section;
  const issues = sectionIssues(draft, section);
  const aiCount = aiCountIn(draft, section);
  const errors = sectionErrors(fieldErrors, section);
  const headingId = sectionDomId(section);
  const stateClass = asked
    ? " rf-section--asked"
    : issues.length > 0
      ? " rf-section--missing"
      : "";
  return (
    <section
      className={`rf-section${stateClass}`}
      aria-labelledby={headingId}
      data-section={section}
    >
      <div className="rf-section-head">
        <h3 id={headingId} tabIndex={-1}>
          {title}
        </h3>
        <span className="rf-section-tools">
          {asked ? <span className="rf-tag">Claude が聞いています</span> : null}
          {aiCount > 0 ? (
            <span className="rf-count">AI が入れた {aiCount} 欄</span>
          ) : null}
          {actions}
        </span>
      </div>
      {issues.map((issue) => (
        <p key={issue.code} className="rf-empty">
          必須: {issue.message}
        </p>
      ))}
      {errors.length > 0 ? (
        <p className="rf-field-error" role="alert">
          {errors.join("／")}
        </p>
      ) : null}
      {children}
    </section>
  );
}

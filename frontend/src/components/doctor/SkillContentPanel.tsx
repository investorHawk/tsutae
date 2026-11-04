import type { AnswerType } from "../../api/types";
import ErrorNote from "./ErrorNote";
import { skillDisplayName, versionLabel } from "./skillLabels";
import type { SkillContentState } from "./useSkillContent";

const ANSWER_LABELS: Readonly<Record<AnswerType, string>> = {
  three_level: "3段階で答える",
  temperature: "体温を入れる",
};

interface SkillContentPanelProps {
  skillName: string;
  version: number | null;
  state: SkillContentState;
}

function Body({ state }: { state: SkillContentState }) {
  const { content, error } = state;
  if (error) {
    return <ErrorNote code={error} prefix="今の中身を出せません" />;
  }
  if (!content) {
    return <p className="d-muted">読み込み中…</p>;
  }
  return (
    <>
      <p className="d-muted">{content.description}</p>
      {content.questions.length > 0 ? (
        <ol className="d-skill-questions" aria-label="今の質問">
          {content.questions.map((q) => (
            <li key={q.key}>
              {q.text}
              <span className="d-skill-q-type">
                （{ANSWER_LABELS[q.answer_type]}）
              </span>
              <code className="d-skill-code">{q.key}</code>
            </li>
          ))}
        </ol>
      ) : null}
      <details className="d-skill-fulltext">
        <summary>SKILL.md の全文</summary>
        <pre>{content.text}</pre>
      </details>
    </>
  );
}

/**
 * D4: 依頼の前に、選んだ Skill の今の中身（質問の一覧・SKILL.md の全文）を見せる。
 * 読み取り専用。質問の一覧は開いておき、全文は折りたたむ。
 */
export default function SkillContentPanel({
  skillName,
  version,
  state,
}: SkillContentPanelProps) {
  if (skillName === "" || version === null) {
    return null;
  }
  return (
    <section className="d-skill-content" aria-label="選んだ Skill の今の中身">
      <details open>
        <summary>
          今の中身（{skillDisplayName(skillName)}・{versionLabel(version)}）
        </summary>
        <Body state={state} />
      </details>
    </section>
  );
}

import type { QuestionRow } from "../../../api/regimenTypes";
import { FieldInput } from "./FieldInput";
import FormSection from "./FormSection";
import type { Parsed } from "./fieldValues";
import { useRegimenForm } from "./formContext";
import { useRowActions } from "./useRowActions";

export const ANSWER_TYPE_LABELS = {
  three_level: "3択",
  temperature: "体温",
} as const;

const asText = (text: string): Parsed<string | null> => ({
  ok: true,
  value: text.trim() === "" ? null : text.trim(),
});

function QuestionRowView({ row }: { row: QuestionRow }) {
  const { locked } = useRegimenForm();
  const { deleteRow } = useRowActions();
  const base = `questions.${row.row_id}`;
  const fever = row.answer_type === "temperature";
  const name = row.label ?? row.key ?? "名前のない質問";
  return (
    <li className="rf-question">
      <FieldInput
        fieldId={`${base}.label`}
        label="短い名前"
        value={row.label ?? ""}
        parse={asText}
        placeholder="例: 下痢"
      />
      <FieldInput
        fieldId={`${base}.text`}
        label="患者に出る文"
        value={row.text ?? ""}
        parse={asText}
        placeholder="例: 下痢はありましたか"
      />
      <FieldInput
        fieldId={`${base}.key`}
        label="key（英小文字）"
        value={row.key ?? ""}
        parse={asText}
        placeholder="例: diarrhea"
        disabled={fever}
      />
      <div className="rf-question-type">
        <span className="rf-field-label">回答の型</span>
        <span>
          {row.answer_type ? ANSWER_TYPE_LABELS[row.answer_type] : "未入力"}
        </span>
      </div>
      <div className="rf-question-ops">
        {fever ? (
          <span className="d-muted">外せない</span>
        ) : (
          <button
            type="button"
            className="rf-row-delete"
            disabled={locked}
            aria-label={`質問「${name}」を消す`}
            onClick={() => void deleteRow("questions", row.row_id)}
          >
            消す
          </button>
        )}
      </div>
    </li>
  );
}

interface QuestionsSectionProps {
  onOpenLibrary: (opener: HTMLButtonElement) => void;
}

/** 患者への質問（スマホに毎日出る）: 短い名前・文・key・型。体温の質問は外せない。 */
export default function QuestionsSection({
  onOpenLibrary,
}: QuestionsSectionProps) {
  const { draft, locked } = useRegimenForm();
  const { addRow, adding } = useRowActions();
  return (
    <FormSection
      section="questions"
      title="患者への質問（スマホに毎日出る）"
      actions={
        <>
          <button
            type="button"
            disabled={locked}
            onClick={(e) => onOpenLibrary(e.currentTarget)}
          >
            部品集から選ぶ
          </button>
          <button
            type="button"
            disabled={locked || adding}
            onClick={() =>
              void addRow("questions", "label", { answer_type: "three_level" })
            }
          >
            ＋ 手で足す
          </button>
        </>
      }
    >
      <ul className="rf-questions" aria-label="患者への質問">
        {draft.form.questions.map((row) => (
          <QuestionRowView key={row.row_id} row={row} />
        ))}
      </ul>
      <p className="rf-fixed-rule">
        固定規則（外せない）: 体温が 38.0℃
        以上なら、患者の画面に決まった文で連絡先を出す
      </p>
    </FormSection>
  );
}

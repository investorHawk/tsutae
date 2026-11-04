import type { AnswerValue } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";

interface ChoiceButtonsProps<V extends AnswerValue> {
  values: readonly V[];
  selected: AnswerValue | undefined;
  onSelect: (value: V) => void;
  disabled?: boolean;
}

/**
 * 大きな選択ボタン（なし／ある／つらい、測っていない／測った）。押したものは aria-pressed。
 * まだ何も選んでいない質問は p-choices--unanswered（全てのボタンを薄い橙にして入力を促す）。
 * 選んだボタンはどの答えでも同じ青（✓ と太枠つき）、選ばなかったボタンは白。
 */
export default function ChoiceButtons<V extends AnswerValue>({
  values,
  selected,
  onSelect,
  disabled = false,
}: ChoiceButtonsProps<V>) {
  const { t } = usePatientStrings();
  const unanswered = selected === undefined || !values.includes(selected as V);
  return (
    <div className={`p-choices${unanswered ? " p-choices--unanswered" : ""}`}>
      {values.map((value) => (
        <button
          key={value}
          type="button"
          className="p-choice"
          aria-pressed={selected === value}
          disabled={disabled}
          onClick={() => onSelect(value)}
        >
          {t(`answer.${value}`)}
        </button>
      ))}
    </div>
  );
}

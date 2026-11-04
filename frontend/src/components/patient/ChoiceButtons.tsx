import type { AnswerValue } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";

interface ChoiceButtonsProps<V extends AnswerValue> {
  values: readonly V[];
  selected: AnswerValue | undefined;
  onSelect: (value: V) => void;
  disabled?: boolean;
}

/** 大きな選択ボタン（なし／ある／つらい、測っていない／測った）。押したものは aria-pressed。 */
export default function ChoiceButtons<V extends AnswerValue>({
  values,
  selected,
  onSelect,
  disabled = false,
}: ChoiceButtonsProps<V>) {
  const { t } = usePatientStrings();
  return (
    <div className="p-choices">
      {values.map((value) => (
        <button
          key={value}
          type="button"
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

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
 * 値ごとの class（p-choice--hard 等）で、選んだ時の見た目を値ごとに変える（P2-1）。
 */
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
          className={`p-choice p-choice--${value}`}
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

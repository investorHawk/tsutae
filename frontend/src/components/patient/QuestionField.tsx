import { useId } from "react";
import type { AnswerValue, Question } from "../../api/types";
import { FEVER_VALUES, THREE_LEVEL_VALUES } from "../../api/types";
import ChoiceButtons from "./ChoiceButtons";
import TemperatureField from "./TemperatureField";

interface QuestionFieldProps {
  question: Question;
  selected: AnswerValue | undefined;
  onSelect: (value: AnswerValue) => void;
  temperatureText: string;
  onTemperatureChange: (value: string) => void;
  temperatureInvalid: boolean;
  disabled?: boolean;
}

/** クローズ質問1問。質問文は API の questions[].text（医師が承認した Skill の文）をそのまま出す。 */
export default function QuestionField({
  question,
  selected,
  onSelect,
  temperatureText,
  onTemperatureChange,
  temperatureInvalid,
  disabled = false,
}: QuestionFieldProps) {
  const labelId = useId();
  const isTemperature = question.answer_type === "temperature";
  return (
    <div className="p-question" role="group" aria-labelledby={labelId}>
      <p id={labelId} className="p-question-text">
        {question.text}
      </p>
      <ChoiceButtons
        values={isTemperature ? FEVER_VALUES : THREE_LEVEL_VALUES}
        selected={selected}
        onSelect={onSelect}
        disabled={disabled}
      />
      {isTemperature && selected === "measured" && (
        <TemperatureField
          value={temperatureText}
          onChange={onTemperatureChange}
          invalid={temperatureInvalid}
          disabled={disabled}
        />
      )}
    </div>
  );
}

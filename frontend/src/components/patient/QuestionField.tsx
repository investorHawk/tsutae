import { useId, useState } from "react";
import type { AnswerValue, Question } from "../../api/types";
import { FEVER_VALUES, THREE_LEVEL_VALUES } from "../../api/types";
import ChoiceButtons from "./ChoiceButtons";
import type { TemperatureProblem } from "./entryForm";
import TemperatureField from "./TemperatureField";

interface QuestionFieldProps {
  question: Question;
  selected: AnswerValue | undefined;
  onSelect: (value: AnswerValue) => void;
  temperatureText: string;
  onTemperatureChange: (value: string) => void;
  /** 送ろうとして体温が不正だったときの問題。正しければ null */
  temperatureError: TemperatureProblem | null;
  disabled?: boolean;
}

/** クローズ質問1問。質問文は API の questions[].text（医師が承認した Skill の文）をそのまま出す。 */
export default function QuestionField({
  question,
  selected,
  onSelect,
  temperatureText,
  onTemperatureChange,
  temperatureError,
  disabled = false,
}: QuestionFieldProps) {
  const labelId = useId();
  const isTemperature = question.answer_type === "temperature";
  // 今「測った」を押して体温の欄が現れた時だけ、その欄に focus する
  const [pressedMeasured, setPressedMeasured] = useState(false);
  const select = (value: AnswerValue) => {
    setPressedMeasured(value === "measured" && selected !== "measured");
    onSelect(value);
  };
  return (
    <div className="p-question" role="group" aria-labelledby={labelId}>
      <p id={labelId} className="p-question-text">
        {question.text}
      </p>
      <ChoiceButtons
        values={isTemperature ? FEVER_VALUES : THREE_LEVEL_VALUES}
        selected={selected}
        onSelect={select}
        disabled={disabled}
      />
      {isTemperature && selected === "measured" && (
        <TemperatureField
          value={temperatureText}
          onChange={onTemperatureChange}
          problem={temperatureError}
          disabled={disabled}
          focusOnShow={pressedMeasured}
        />
      )}
    </div>
  );
}

import type { AnswerValue, Question } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import {
  setAnswer,
  setTemperatureText,
  type EntryFormState,
} from "./entryForm";
import QuestionField from "./QuestionField";

type FormUpdate = (update: (prev: EntryFormState) => EntryFormState) => void;

interface QuestionListProps {
  questions: readonly Question[];
  form: EntryFormState;
  onChange: FormUpdate;
  /** 体温が不正と出す質問の key（送ろうとした後だけ中身がある） */
  invalidTemperatureKeys: ReadonlySet<string>;
  disabled: boolean;
}

/** 段階1 のクローズ質問（質問集の順）。押した答えは新しい状態として onChange に渡す。 */
export default function QuestionList({
  questions,
  form,
  onChange,
  invalidTemperatureKeys,
  disabled,
}: QuestionListProps) {
  const { t } = usePatientStrings();
  return (
    <section>
      <h2>{t("today.questions_title")}</h2>
      {questions.map((question) => (
        <QuestionField
          key={question.key}
          question={question}
          selected={form.answers[question.key]}
          onSelect={(value: AnswerValue) =>
            onChange((prev) => setAnswer(prev, question.key, value))
          }
          temperatureText={form.temperatureTexts[question.key] ?? ""}
          onTemperatureChange={(text) =>
            onChange((prev) => setTemperatureText(prev, question.key, text))
          }
          temperatureInvalid={invalidTemperatureKeys.has(question.key)}
          disabled={disabled}
        />
      ))}
    </section>
  );
}

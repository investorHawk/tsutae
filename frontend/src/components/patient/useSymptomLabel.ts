import { useCallback } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";

const PREVIOUS_QUESTION_KEY = "history.previous_question";

/**
 * 項目の名前（一行の要約と回答の表で同じ規則）。短い症状名（symptom.<key>）、
 * 無ければ質問文、それも無ければ「以前の質問」（history.previous_question）。
 */
export function useSymptomLabel(): (
  questionKey: string,
  questionText: string | null,
) => string {
  const { t, has } = usePatientStrings();
  return useCallback(
    (questionKey: string, questionText: string | null): string => {
      const key = `symptom.${questionKey}`;
      if (has(key)) {
        return t(key);
      }
      return questionText ?? t(PREVIOUS_QUESTION_KEY);
    },
    [t, has],
  );
}

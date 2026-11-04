import type { AnswerValue, ThreeLevel } from "../../api/types";
import { THREE_LEVEL_VALUES } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import { fillTemplate } from "../../strings/template";
import type { SummaryAnswer } from "./entrySummary";
import { useSymptomLabel } from "./useSymptomLabel";

function isThreeLevel(value: AnswerValue): value is ThreeLevel {
  return (THREE_LEVEL_VALUES as readonly AnswerValue[]).includes(value);
}

/** 3列の行。選んだ欄だけに答えの文字（太字）を出し、他の欄は空（小さな○は CSS で描く）。 */
function ThreeLevelCells({ value }: { value: ThreeLevel }) {
  const { t } = usePatientStrings();
  return (
    <>
      {THREE_LEVEL_VALUES.map((v) =>
        v === value ? (
          <td key={v} className="p-answer-cell p-answer-cell--chosen">
            <strong>{t(`answer.${v}`)}</strong>
          </td>
        ) : (
          <td key={v} className="p-answer-cell" />
        ),
      )}
    </>
  );
}

/**
 * 3列をまたぐ欄（体温「測った 36.8℃」・「測っていない」）。想定外の組み合わせも
 * 答えの文字を出す（捨てない）。
 */
function WideCell({ answer }: { answer: SummaryAnswer }) {
  const { t } = usePatientStrings();
  const temperature =
    answer.value === "measured" && typeof answer.temperature === "number"
      ? fillTemplate(t("history.temperature_value"), {
          value: answer.temperature.toFixed(1),
        })
      : null;
  return (
    <td className="p-answer-wide" colSpan={THREE_LEVEL_VALUES.length}>
      <strong>
        {t(`answer.${answer.value}`)}
        {temperature !== null && ` ${temperature}`}
      </strong>
    </td>
  );
}

/**
 * 回答の表（これまでの記録の詳しい表示と、記録した後の確認で同じ部品）。
 * 列見出しは なし／ある／つらい、行見出しは短い症状名。読み上げは「しびれ ある」。
 */
export default function AnswerTable({
  answers,
}: {
  answers: readonly SummaryAnswer[];
}) {
  const { t } = usePatientStrings();
  const label = useSymptomLabel();
  const withColumns = answers.some((a) => isThreeLevel(a.value));
  return (
    <table className="p-answers">
      {/* 列の幅（table-layout: fixed）。見出しの行が無い時も3列の幅をそろえる */}
      <colgroup>
        <col />
        <col className="p-answers-col" span={THREE_LEVEL_VALUES.length} />
      </colgroup>
      {withColumns && (
        <thead>
          <tr>
            <td />
            {THREE_LEVEL_VALUES.map((v) => (
              <th key={v} scope="col">
                {t(`answer.${v}`)}
              </th>
            ))}
          </tr>
        </thead>
      )}
      <tbody>
        {answers.map((answer, i) => (
          <tr key={`${i}-${answer.questionKey}`}>
            <th scope="row">
              {label(answer.questionKey, answer.questionText)}
            </th>
            {isThreeLevel(answer.value) ? (
              <ThreeLevelCells value={answer.value} />
            ) : (
              <WideCell answer={answer} />
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

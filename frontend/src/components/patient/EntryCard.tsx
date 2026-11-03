import type { PatientAnswer, PatientEntry } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import { formatRecordedAt } from "./history";

const PREVIOUS_QUESTION_KEY = "history.previous_question";

/**
 * 回答1つ。質問文は記録時点の質問集の文（API の question_text）。見つからなかった
 * （null・省略）ときは history.previous_question を出し、回答の値は必ず出す（捨てない）。
 */
function AnswerRow({ answer }: { answer: PatientAnswer }) {
  const { t } = usePatientStrings();
  const temperature =
    answer.value === "measured" && typeof answer.temperature === "number"
      ? answer.temperature.toFixed(1)
      : null;
  return (
    <div>
      <dt>{answer.question_text ?? t(PREVIOUS_QUESTION_KEY)}</dt>
      <dd>
        {t(`answer.${answer.value}`)}
        {temperature !== null && (
          <>
            {" "}
            {t("temperature.label")} {temperature}
          </>
        )}
      </dd>
    </div>
  );
}

/** 自分の記録1件（P2）。編集はできない。AI のまとめは出さない（API にも無い）。 */
export default function EntryCard({ entry }: { entry: PatientEntry }) {
  const { t } = usePatientStrings();
  return (
    <li className="p-entry">
      <p>
        <time dateTime={entry.recorded_at}>{formatRecordedAt(entry)}</time>
      </p>
      {entry.by_proxy && <p>{t("history.proxy")}</p>}
      {entry.kind === "too_sick" && <p>{t("history.too_sick")}</p>}
      {entry.answers.length > 0 && (
        <dl>
          {entry.answers.map((answer, i) => (
            <AnswerRow key={`${i}-${answer.question_key}`} answer={answer} />
          ))}
        </dl>
      )}
      {entry.free_text && (
        <>
          <p>{t("history.free_text")}</p>
          <p style={{ whiteSpace: "pre-wrap" }}>{entry.free_text}</p>
        </>
      )}
    </li>
  );
}

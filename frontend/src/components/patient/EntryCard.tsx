import type { PatientAnswer, PatientEntry } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import { summarizeEntry, summarySourceOf } from "./entrySummary";
import { formatRecordedAt } from "./history";
import SummaryLine from "./SummaryLine";

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

/**
 * 自分の記録1件（P2）。一行の要約（日時と「しびれ つらい／下痢 ある」）を押すと、
 * 質問文つきの詳しい内容が開く（details。キーボードでも開ける）。編集はできない。
 * AI のまとめは出さない（API にも無い）。
 */
export default function EntryCard({ entry }: { entry: PatientEntry }) {
  const { t } = usePatientStrings();
  const items = summarizeEntry(summarySourceOf(entry));
  return (
    <li className="p-entry">
      <details>
        <summary className="p-entry-summary">
          <time className="p-entry-time" dateTime={entry.recorded_at}>
            {formatRecordedAt(entry, t)}
          </time>
          <SummaryLine items={items} />
        </summary>
        <div className="p-entry-detail">
          {entry.by_proxy && <p>{t("history.proxy")}</p>}
          {entry.kind === "too_sick" && <p>{t("history.too_sick")}</p>}
          {entry.answers.length > 0 && (
            <dl>
              {entry.answers.map((answer, i) => (
                <AnswerRow
                  key={`${i}-${answer.question_key}`}
                  answer={answer}
                />
              ))}
            </dl>
          )}
          {entry.free_text && (
            <>
              <p>{t("history.free_text")}</p>
              <p className="p-entry-free-text">{entry.free_text}</p>
            </>
          )}
        </div>
      </details>
    </li>
  );
}

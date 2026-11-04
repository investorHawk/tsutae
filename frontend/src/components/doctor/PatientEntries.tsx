import type { DoctorEntry } from "../../api/types";
import { answerText } from "./answerLabels";
import ErrorNote from "./ErrorNote";
import type { PatientRecords } from "./usePatientRecords";

const NONE = "—";

function Answers({ entry }: { entry: DoctorEntry }) {
  if (entry.kind === "too_sick") {
    return <span>つらくて書けない</span>;
  }
  if (entry.answers.length === 0) {
    return <span className="d-muted">{NONE}</span>;
  }
  return (
    <ul className="d-answers">
      {entry.answers.map((a) => (
        <li
          key={a.question_key}
          className={a.value === "hard" ? "d-answer--hard" : undefined}
        >
          {answerText(a)}
        </li>
      ))}
    </ul>
  );
}

/**
 * D2 の「記録」の節（D4-1）。直近の記録を新しい順に、日付・クローズ回答の短い表記・
 * 自由記載の有無・代理入力の印で並べる。自由記載の原文は出さない（原文は D6 だけ）。
 */
export default function PatientEntries({
  entries,
}: {
  entries: PatientRecords["entries"];
}) {
  const loaded = entries.value;
  return (
    <section className="d-section" aria-labelledby="d-sec-entries">
      <h2 id="d-sec-entries">記録</h2>
      {entries.error ? (
        <ErrorNote code={entries.error} prefix="記録を取れません" />
      ) : null}
      {loaded && loaded.items.length === 0 ? (
        <p className="d-muted">まだ記録はありません</p>
      ) : null}
      {loaded && loaded.items.length > 0 ? (
        <>
          <p className="d-muted">
            {loaded.total > loaded.items.length
              ? `全 ${loaded.total} 件のうち新しい ${loaded.items.length} 件。`
              : `${loaded.total} 件。`}
            自由記載の原文はここには出しません（レポートの引用と、伏せ字漏れの疑いがあれば未処理の記載で見られます）。
          </p>
          <table className="d-table d-table--middle d-entries">
            <thead>
              <tr>
                <th scope="col">記録日</th>
                <th scope="col">クローズ回答</th>
                <th scope="col">自由記載</th>
                <th scope="col">代理</th>
              </tr>
            </thead>
            <tbody>
              {loaded.items.map((entry) => (
                <tr key={entry.id}>
                  <td className="d-nowrap">{entry.record_date}</td>
                  <td>
                    <Answers entry={entry} />
                  </td>
                  <td>{entry.has_free_text ? "あり" : NONE}</td>
                  <td>{entry.by_proxy ? "代" : NONE}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </section>
  );
}

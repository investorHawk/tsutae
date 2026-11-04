import type { PatientEntry } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import EntryDetail from "./EntryDetail";
import { summarizeEntry, summarySourceOf } from "./entrySummary";
import { formatRecordedAt } from "./history";
import SummaryLine from "./SummaryLine";

/**
 * 自分の記録1件（P2）。一行の要約（日時と「しびれ つらい／下痢 ある」）を押すと、
 * 詳しい内容（回答の表と書いたこと）が開く（details。キーボードでも開ける）。
 * 編集はできない。AI のまとめは出さない（API にも無い）。
 * 表の行の名前は短い症状名。無ければ記録時点の質問文（API の question_text）、それも
 * 無ければ history.previous_question。回答の値は必ず出す（捨てない）。
 */
export default function EntryCard({ entry }: { entry: PatientEntry }) {
  const { t } = usePatientStrings();
  const source = summarySourceOf(entry);
  const items = summarizeEntry(source);
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
          <EntryDetail
            byProxy={entry.by_proxy}
            source={source}
            showFreeTextBody
          />
        </div>
      </details>
    </li>
  );
}

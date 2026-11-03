import { listEntries } from "../../api/patient";
import type { PatientEntry } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import EntryCard from "./EntryCard";
import { newestFirst } from "./history";
import { LoadFailed, Loading } from "./LoadStatus";
import { ErrorMessage } from "./Messages";
import { NOT_REGISTERED_KEY, isNotRegistered } from "./patientApi";
import { useAsync } from "./useAsync";

/** 記録を読む（新しい順）。質問文は記録の answers[].question_text（記録時点の質問集の文）。 */
async function loadHistory(pid: string): Promise<PatientEntry[]> {
  const { entries } = await listEntries(pid);
  return newestFirst(entries);
}

/** 自分の記録の一覧（新しい順）。読めなければ common.load_failed と「読み直す」。 */
export default function HistoryList({ pid }: { pid: string }) {
  const { t } = usePatientStrings();
  const loaded = useAsync(() => loadHistory(pid), pid);

  if (loaded.status === "loading") {
    return <Loading />;
  }
  if (loaded.status === "error") {
    return isNotRegistered(loaded.error) ? (
      <ErrorMessage messageKey={NOT_REGISTERED_KEY} />
    ) : (
      <LoadFailed onReload={loaded.reload} />
    );
  }
  const entries = loaded.data;
  if (entries.length === 0) {
    return <p>{t("history.empty")}</p>;
  }
  return (
    <ul className="p-entries" aria-label={t("history.title")}>
      {entries.map((entry) => (
        <EntryCard key={entry.id} entry={entry} />
      ))}
    </ul>
  );
}

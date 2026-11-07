import { getVisitDays } from "../../api/patientDevice";
import { listDeviceEntries } from "../../patient/deviceStore";
import { usePatientStrings } from "../../strings/PatientStrings";
import EntryCard from "./EntryCard";
import { type HistoryRow, historyRows } from "./historyRows";
import { LoadFailed, Loading } from "./LoadStatus";
import NotRegistered from "./NotRegistered";
import { isNotRegistered } from "./patientApi";
import { useAsync } from "./useAsync";
import VisitDivider from "./VisitDivider";

interface HistoryData {
  /** 記録が1件も無い（受診日の区切りだけのことがある） */
  noEntries: boolean;
  rows: HistoryRow[];
}

/**
 * 端末の記録とサーバーの受診日を読み、新しい順の行にする（受診日の区切りは受付の時刻の位置）。
 * 質問文は記録の answers[].question_text（記録時点の質問集の文）。
 */
async function loadHistory(pid: string): Promise<HistoryData> {
  const [entries, { visits }] = await Promise.all([
    listDeviceEntries(pid),
    getVisitDays(pid),
  ]);
  return {
    noEntries: entries.length === 0,
    rows: historyRows(entries, visits),
  };
}

function Row({ row }: { row: HistoryRow }) {
  return row.kind === "entry" ? (
    <EntryCard entry={row.entry} />
  ) : (
    <VisitDivider visit={row.visit} />
  );
}

/**
 * このスマホの記録の一覧（新しい順）。受診日（受付をした日）は区切りの行で示す。
 * 記録が無くても受診日があれば、history.empty の文の下に区切りだけを並べる。
 * 読めなければ common.load_failed と「読み直す」。
 */
export default function HistoryList({ pid }: { pid: string }) {
  const { t } = usePatientStrings();
  const loaded = useAsync(() => loadHistory(pid), pid);

  if (loaded.status === "loading") {
    return <Loading />;
  }
  if (loaded.status === "error") {
    return isNotRegistered(loaded.error) ? (
      <NotRegistered />
    ) : (
      <LoadFailed onReload={loaded.reload} />
    );
  }
  const { noEntries, rows } = loaded.data;
  return (
    <>
      {noEntries && <p>{t("history.empty")}</p>}
      {rows.length > 0 && (
        <ul className="p-entries" aria-label={t("history.title")}>
          {rows.map((row) => (
            <Row
              key={
                row.kind === "entry"
                  ? `entry-${row.entry.client_entry_id}`
                  : `visit-${row.visit.visit_date}`
              }
              row={row}
            />
          ))}
        </ul>
      )}
    </>
  );
}

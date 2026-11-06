import { EntryGridRow, VisitDayRow } from "./EntryGridRow";
import { gridColumns, gridRows } from "./entryGrid";
import ErrorNote from "./ErrorNote";
import type { PatientRecords } from "./usePatientRecords";
import "./board.css";

/** 列: 記録日・Day・（症状ごと・体温）・自由記載・代 */
const FIXED_COLUMNS = 4;

/**
 * D2 の「記録」の節（D4-1）。直近の記録の経過表: 日付の行 × 症状の列（question_key ごと）。
 * 受付の時刻の位置に受診日の行（緑の線）を入れる（受診は「受診」の節と同じ応答）。
 * 自由記載の原文は出さない（有無だけ。原文は D6 だけ）。はみ出す時は表だけ横に送る。
 * 記録の中身は受付の間だけサーバーにある（plan-device-records §5.7）。
 */
export default function PatientEntries({
  entries,
  visits,
}: {
  entries: PatientRecords["entries"];
  visits: PatientRecords["visits"];
}) {
  const loaded = entries.value;
  const items = loaded?.items ?? [];
  const visitList = visits.value ?? [];
  const columns = gridColumns(items);
  const truncated = loaded !== null && loaded.total > items.length;
  const rows = gridRows(items, visitList, truncated);
  const colSpan = FIXED_COLUMNS + Math.max(columns.length, 1);
  return (
    <section className="d-section" aria-labelledby="d-sec-entries">
      <h2 id="d-sec-entries">記録</h2>
      {entries.error ? (
        <ErrorNote code={entries.error} prefix="記録を取れません" />
      ) : null}
      {loaded && items.length === 0 ? (
        <p className="d-muted">
          記録は患者さんのスマホにあります。受付の後に表示されます
        </p>
      ) : null}
      {loaded && items.length > 0 ? (
        <p className="d-muted">
          {truncated
            ? `全 ${loaded.total} 件のうち新しい ${items.length} 件。`
            : `${loaded.total} 件。`}
          自由記載の原文はここには出しません（レポートの引用と、伏せ字漏れの疑いがあれば未処理の記載で見られます）。
        </p>
      ) : null}
      {loaded && rows.length > 0 ? (
        <div className="d-grid-scroll">
          <table className="d-table d-table--middle d-grid d-entries">
            <thead>
              <tr>
                <th scope="col">記録日</th>
                <th scope="col">Day</th>
                {columns.length > 0 ? (
                  columns.map((c) => (
                    <th key={c.key} scope="col" className="d-grid-cell">
                      {c.label}
                    </th>
                  ))
                ) : (
                  <th scope="col">回答</th>
                )}
                <th scope="col">自由記載</th>
                <th scope="col">代理</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) =>
                row.kind === "entry" ? (
                  <EntryGridRow
                    key={`e${row.entry.id}`}
                    entry={row.entry}
                    columns={columns}
                  />
                ) : (
                  <VisitDayRow
                    key={`v${row.visit.visit_date}`}
                    visit={row.visit}
                    colSpan={colSpan}
                  />
                ),
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

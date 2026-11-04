import type { PatientVisit } from "../../api/types";
import { formatDay } from "./dayLabel";
import ReportLink from "./ReportLink";
import StatusBadge from "./StatusBadge";
import UnprocessedLink from "./UnprocessedLink";
import type { PatientRecords } from "./usePatientRecords";
import "./board.css";

/** 印刷待ちの一覧（D3）に出る受診: 受付番号が残っている generating・ready・failed。 */
export function isOpenVisit(visit: PatientVisit): boolean {
  return visit.reception_no !== null && visit.status !== "printed";
}

/**
 * D2 のページの上（コースより上）に置く、この患者の印刷待ち・生成中の受診。受付番号・状態・
 * 受付・レポートを開く・要確認（未処理の件数）。無ければ節ごと出さない。
 */
export default function OpenVisits({
  visits,
}: {
  visits: PatientRecords["visits"];
}) {
  const open = (visits.value ?? []).filter(isOpenVisit);
  if (open.length === 0) {
    return null;
  }
  return (
    <section
      className="d-section d-open-visits"
      aria-labelledby="d-sec-open-visits"
    >
      <h2 id="d-sec-open-visits">印刷待ちの受診</h2>
      <table className="d-table d-table--middle">
        <thead>
          <tr>
            <th scope="col">受付番号</th>
            <th scope="col">状態</th>
            <th scope="col">受付</th>
            <th scope="col">レポート</th>
            <th scope="col">未処理</th>
          </tr>
        </thead>
        <tbody>
          {open.map((visit) => (
            <tr key={visit.id}>
              <td className="d-reception">{visit.reception_no}</td>
              <td>
                <span className="d-badges">
                  <StatusBadge status={visit.status} />
                  {visit.fallback && visit.report_available ? (
                    <span className="d-status-note">AI変換なし</span>
                  ) : null}
                </span>
              </td>
              <td className="d-nowrap">{formatDay(visit.created_at)}</td>
              <td>
                {visit.report_available ? (
                  <ReportLink visitId={visit.id} />
                ) : null}
              </td>
              <td>
                {visit.unprocessed_count > 0 ? (
                  <UnprocessedLink
                    visitId={visit.id}
                    count={visit.unprocessed_count}
                  />
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

import { reportUrl } from "../../api/doctor";
import type { PatientVisit } from "../../api/types";
import ErrorNote from "./ErrorNote";
import StatusBadge from "./StatusBadge";
import UnprocessedLink from "./UnprocessedLink";
import type { PatientRecords } from "./usePatientRecords";

const NONE = "—";

/** 状態。受付番号が消えていて印刷済みでなければ期限切れ（24 時間で消えた）。 */
function VisitState({ visit }: { visit: PatientVisit }) {
  if (visit.reception_no === null && visit.status !== "printed") {
    return <span className="d-status-note">期限切れ</span>;
  }
  return (
    <span className="d-badges">
      <StatusBadge status={visit.status} />
      {visit.fallback && visit.report_available ? (
        <span className="d-status-note">AI変換なし</span>
      ) : null}
    </span>
  );
}

function VisitLinks({ visit }: { visit: PatientVisit }) {
  const unprocessed =
    visit.reception_no !== null && visit.unprocessed_count > 0;
  if (!visit.report_available && !unprocessed) {
    return null;
  }
  return (
    <span className="d-actions">
      {visit.report_available ? (
        <a href={reportUrl(visit.id)} target="_blank" rel="noopener noreferrer">
          レポートを開く
        </a>
      ) : null}
      {unprocessed ? (
        <UnprocessedLink visitId={visit.id} count={visit.unprocessed_count} />
      ) : null}
    </span>
  );
}

/**
 * D2 の「受診」の節（D4-1）。新しい順に、受診日・受付番号・状態・レポート。
 * レポートは印刷済みか 24 時間で消えるので、開けるのは印刷待ちの受診だけ。
 */
export default function PatientVisits({
  visits,
}: {
  visits: PatientRecords["visits"];
}) {
  const list = visits.value;
  return (
    <section className="d-section" aria-labelledby="d-sec-visits">
      <h2 id="d-sec-visits">受診</h2>
      <p className="d-muted">
        レポートは印刷済みにするか 24
        時間で消えます。開けるのは印刷待ちの受診だけです。
      </p>
      {visits.error ? (
        <ErrorNote code={visits.error} prefix="受診を取れません" />
      ) : null}
      {list?.length === 0 ? (
        <p className="d-muted">まだ受診はありません</p>
      ) : null}
      {list && list.length > 0 ? (
        <table className="d-table d-table--middle d-patient-visits">
          <thead>
            <tr>
              <th scope="col">受診日</th>
              <th scope="col">受付番号</th>
              <th scope="col">状態</th>
              <th scope="col">レポート</th>
            </tr>
          </thead>
          <tbody>
            {list.map((visit) => (
              <tr key={visit.id}>
                <td className="d-nowrap">{visit.visit_date}</td>
                <td className="d-reception">{visit.reception_no ?? NONE}</td>
                <td>
                  <VisitState visit={visit} />
                </td>
                <td>
                  <VisitLinks visit={visit} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

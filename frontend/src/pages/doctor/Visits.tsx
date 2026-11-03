import { useState } from "react";
import { listVisits, markPrinted, regenerateVisit } from "../../api/doctor";
import type { VisitStatus, VisitSummary } from "../../api/types";
import ErrorNote from "../../components/doctor/ErrorNote";
import { errorCode, isUnauthorized } from "../../components/doctor/errors";
import { formatTime } from "../../components/doctor/format";
import { isVisitSummary } from "../../components/doctor/guards";
import { listOf } from "../../components/doctor/input";
import { usePolling } from "../../components/doctor/usePolling";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import VisitRow from "../../components/doctor/VisitRow";
import "../../components/doctor/doctor-ui.css";

const VISITS_POLL_MS = 5000;

async function fetchVisits(): Promise<VisitSummary[]> {
  return listOf<VisitSummary>(await listVisits(), "visits", isVisitSummary);
}

function countBy(visits: readonly VisitSummary[], status: VisitStatus) {
  return visits.filter((v) => v.status === status).length;
}

function Summary({ visits }: { visits: readonly VisitSummary[] }) {
  const failed = countBy(visits, "failed");
  const parts = [
    `印刷待ち ${countBy(visits, "ready")} 件`,
    `生成中 ${countBy(visits, "generating")} 件`,
    ...(failed > 0 ? [`失敗 ${failed} 件`] : []),
  ];
  return <p className="d-summary">{parts.join(" ・ ")}</p>;
}

interface ActionError {
  /** 何が失敗したか（「印刷済みにできませんでした」など） */
  prefix: string;
  code: string;
}

/** D3 印刷待ち。5秒ごとに取り直す。 */
export default function Visits() {
  const handleError = useDoctorApiError();
  const [actionError, setActionError] = useState<ActionError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const polling = usePolling(fetchVisits, VISITS_POLL_MS, {
    onError: (err) => {
      handleError(err);
      return isUnauthorized(err);
    },
  });
  const visits = polling.data;

  async function handlePrinted(visit: VisitSummary) {
    setActionError(null);
    setNotice(null);
    try {
      await markPrinted(visit.id);
      setNotice(`受付 ${visit.reception_no} のレポートを削除しました`);
    } catch (err) {
      setActionError({
        prefix: "印刷済みにできませんでした",
        code: handleError(err),
      });
    }
    polling.refresh();
  }

  async function handleRegenerate(visit: VisitSummary) {
    setActionError(null);
    setNotice(null);
    try {
      await regenerateVisit(visit.id);
      setNotice(`受付 ${visit.reception_no} を AI でもう一度変換しています`);
    } catch (err) {
      setActionError({
        prefix: "もう一度変換できませんでした",
        code: handleError(err),
      });
    }
    polling.refresh();
  }

  return (
    <section className="page">
      <h1>印刷待ち</h1>
      <div className="d-toolbar">
        {visits ? <Summary visits={visits} /> : null}
        <span className="d-muted d-live">
          5秒ごとに更新
          {polling.updatedAt
            ? `（最終 ${formatTime(polling.updatedAt.toISOString())}）`
            : ""}
        </span>
      </div>
      {polling.error ? (
        <ErrorNote code={errorCode(polling.error)} prefix="一覧を取れません" />
      ) : null}
      <p role="status" className="d-ok">
        {notice ?? ""}
      </p>
      {actionError ? (
        <ErrorNote code={actionError.code} prefix={actionError.prefix} />
      ) : null}
      {visits?.length === 0 ? (
        <p className="d-muted">受付はまだありません</p>
      ) : null}
      {visits && visits.length > 0 ? (
        <table className="d-table d-visits">
          <thead>
            <tr>
              <th scope="col">受付番号</th>
              <th scope="col">仮名ID</th>
              <th scope="col">状態</th>
              <th scope="col">受付</th>
              <th scope="col">未処理</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {visits.map((visit) => (
              <VisitRow
                key={visit.id}
                visit={visit}
                onPrinted={handlePrinted}
                onRegenerate={handleRegenerate}
              />
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

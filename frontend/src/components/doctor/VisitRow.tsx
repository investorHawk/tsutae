import { Link } from "react-router-dom";
import { reportUrl } from "../../api/doctor";
import type { VisitSummary } from "../../api/types";
import { formatDateTime } from "./format";
import StatusBadge from "./StatusBadge";
import TwoStepButton from "./TwoStepButton";

interface VisitRowProps {
  visit: VisitSummary;
  onPrinted: (visitId: number) => Promise<void>;
}

function Actions({ visit, onPrinted }: VisitRowProps) {
  switch (visit.status) {
    case "ready":
      return (
        <div className="d-actions">
          <a
            className="d-linkbutton d-linkbutton--primary"
            href={reportUrl(visit.id)}
            target="_blank"
            rel="noopener noreferrer"
          >
            印刷
          </a>
          <TwoStepButton
            label="印刷済み"
            prompt="レポート・変換結果・受付番号を削除します。印刷は済みましたか？"
            confirmLabel="削除する（印刷済み）"
            onConfirm={() => onPrinted(visit.id)}
          />
          <Link className="d-sublink" to={`/doctor/pipeline/${visit.id}`}>
            変換ログ
          </Link>
        </div>
      );
    case "generating":
      return (
        <div className="d-actions">
          <Link className="d-linkbutton" to={`/doctor/pipeline/${visit.id}`}>
            変換の様子を見る
          </Link>
        </div>
      );
    case "failed":
      return (
        <div className="d-actions">
          <span className="d-muted">レポートを作れませんでした</span>
          <Link className="d-sublink" to={`/doctor/pipeline/${visit.id}`}>
            変換ログ
          </Link>
        </div>
      );
  }
}

/**
 * D3 の1行。受付番号・仮名ID・状態・AI変換なし・未処理・操作。
 * 一覧に出るのは generating・ready・failed だけ（印刷済み・期限切れは API が出さない）。
 */
export default function VisitRow({ visit, onPrinted }: VisitRowProps) {
  return (
    <tr className={`d-visit d-visit--${visit.status}`}>
      <td className="d-reception">{visit.reception_no}</td>
      <td>
        <code>{visit.patient_id}</code>
      </td>
      <td>
        <span className="d-badges">
          <StatusBadge status={visit.status} />
          {visit.fallback ? (
            <span className="d-badge d-badge--fallback">AI変換なし</span>
          ) : null}
        </span>
      </td>
      <td>{formatDateTime(visit.created_at)}</td>
      <td>
        {visit.unprocessed_count > 0 ? (
          <Link
            className="d-badge d-badge--warn"
            to={`/doctor/unprocessed/${visit.id}`}
          >
            未処理 {visit.unprocessed_count} 件
          </Link>
        ) : (
          <span className="d-muted">—</span>
        )}
      </td>
      <td>
        <Actions visit={visit} onPrinted={onPrinted} />
      </td>
    </tr>
  );
}

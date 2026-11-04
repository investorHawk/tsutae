import { useState } from "react";
import { Link } from "react-router-dom";
import { reportUrl } from "../../api/doctor";
import type { VisitSummary } from "../../api/types";
import { formatDateTime } from "./format";
import PrintButton from "./PrintButton";
import RegenerateButton from "./RegenerateButton";
import StatusBadge from "./StatusBadge";
import TwoStepButton from "./TwoStepButton";
import UnprocessedLink from "./UnprocessedLink";

interface VisitRowProps {
  visit: VisitSummary;
  /** 印刷済みの2段目で呼ぶ（受付番号の知らせのために受診ごと渡す） */
  onPrinted: (visit: VisitSummary) => Promise<void>;
  /** 「AI でもう一度変換」で呼ぶ（AI変換なしの ready・failed の行だけに出す） */
  onRegenerate: (visit: VisitSummary) => Promise<void>;
}

function Actions({ visit, onPrinted, onRegenerate }: VisitRowProps) {
  // 「AI でもう一度変換」を依頼している間は、同じ行の印刷・印刷済みを押せない
  // （サーバーも生成中の印刷済みを 409 にするが、押せる見た目にしない）
  const [regenerating, setRegenerating] = useState(false);
  async function regenerateThis() {
    setRegenerating(true);
    try {
      await onRegenerate(visit);
    } finally {
      setRegenerating(false);
    }
  }
  const regenerate = <RegenerateButton onRegenerate={regenerateThis} />;
  switch (visit.status) {
    case "ready":
      return (
        <div className="d-actions">
          <PrintButton url={reportUrl(visit.id)} disabled={regenerating} />
          <TwoStepButton
            label="印刷済み"
            prompt="レポート・変換結果・受付番号を削除します。印刷は済みましたか？"
            confirmLabel="削除する（印刷済み）"
            onConfirm={() => onPrinted(visit)}
            disabled={regenerating}
          />
          {visit.fallback ? regenerate : null}
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
          {regenerate}
          <Link className="d-sublink" to={`/doctor/pipeline/${visit.id}`}>
            変換ログ
          </Link>
        </div>
      );
  }
}

/**
 * D3 の1行。受付番号・仮名ID・状態（主の状態のバッジと、副の注記「AI変換なし」）・
 * 未処理・操作。
 * 一覧に出るのは generating・ready・failed だけ（印刷済み・期限切れは API が出さない）。
 * AI変換なしの ready と failed には「AI でもう一度変換」を出す（Claude の一時的な失敗の後）。
 */
export default function VisitRow({
  visit,
  onPrinted,
  onRegenerate,
}: VisitRowProps) {
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
            <span className="d-status-note">AI変換なし</span>
          ) : null}
        </span>
      </td>
      <td>{formatDateTime(visit.created_at)}</td>
      <td>
        {visit.unprocessed_count > 0 ? (
          <UnprocessedLink visitId={visit.id} count={visit.unprocessed_count} />
        ) : (
          <span className="d-muted">—</span>
        )}
      </td>
      <td>
        <Actions
          visit={visit}
          onPrinted={onPrinted}
          onRegenerate={onRegenerate}
        />
      </td>
    </tr>
  );
}

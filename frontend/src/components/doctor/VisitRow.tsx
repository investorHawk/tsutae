import { useState } from "react";
import { Link } from "react-router-dom";
import { reportUrl } from "../../api/doctor";
import type { VisitSummary } from "../../api/types";
import { formatDay } from "./dayLabel";
import PrintButton from "./PrintButton";
import RegenerateButton from "./RegenerateButton";
import ReportLink from "./ReportLink";
import StatusBadge from "./StatusBadge";
import TwoStepButton from "./TwoStepButton";
import UnprocessedLink from "./UnprocessedLink";
import "./board.css";

interface VisitRowProps {
  visit: VisitSummary;
  /** 印刷済みにするの2段目で呼ぶ（受付番号の知らせのために受診ごと渡す） */
  onPrinted: (visit: VisitSummary) => Promise<void>;
  /** 「AI でもう一度変換」で呼ぶ（AI変換なし・追加の記録ありの ready と failed の行だけに出す） */
  onRegenerate: (visit: VisitSummary) => Promise<void>;
}

/** 「印刷済みにする」の確かめの文（押した後の流れは D3 のまま）。 */
export const PRINTED_PROMPT =
  "レポート・変換結果・受付番号を削除します。印刷は済みましたか？";

/** 変換し直しが失敗して、前のレポートだけが残っている行の文。 */
const PREVIOUS_REPORT_NOTE =
  "作り直せませんでした。前のレポートを印刷できます（新しい記録が入っていないことがあります）";

/**
 * 2台目のスマホの記録が届いた受診の札（plan-device-records §6）。「作り直しました」は、先に別の
 * タブで開いたレポートが古いままであることを知らせる。生成中は「生成中」のバッジだけにする。
 */
function RecordsAddedNotes({ visit }: { visit: VisitSummary }) {
  return (
    <>
      {visit.status === "ready" && visit.regen_count > 0 ? (
        <span className="d-status-note">記録が追加され、作り直しました</span>
      ) : null}
      {visit.status !== "generating" && visit.regen_pending ? (
        <span className="d-status-note">追加の記録あり</span>
      ) : null}
    </>
  );
}

interface PrintActionsProps {
  visit: VisitSummary;
  onPrinted: VisitRowProps["onPrinted"];
  disabled: boolean;
}

function PrintActions({ visit, onPrinted, disabled }: PrintActionsProps) {
  return (
    <>
      <PrintButton url={reportUrl(visit.id)} disabled={disabled} />
      <TwoStepButton
        label="印刷済みにする"
        prompt={PRINTED_PROMPT}
        confirmLabel="削除する（印刷済み）"
        onConfirm={() => onPrinted(visit)}
        disabled={disabled}
      />
    </>
  );
}

function PipelineLink({ visitId }: { visitId: number }) {
  return (
    <Link className="d-sublink" to={`/doctor/pipeline/${visitId}`}>
      変換ログ
    </Link>
  );
}

/**
 * 操作の列: 左に主の操作（印刷＝青の塗り）と副の操作（印刷済みにする＝白地に枠・
 * AI でもう一度変換）、右に小さなリンク（レポートを開く・変換ログ）。どの状態の行も
 * 同じ2つの組に分けて、行ごとに並びをそろえる。
 */
function Actions({ visit, onPrinted, onRegenerate }: VisitRowProps) {
  // 「AI でもう一度変換」を依頼している間は、同じ行の印刷・印刷済みにするを押せない
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
        <div className="d-visit-ops">
          <div className="d-actions">
            <PrintActions
              visit={visit}
              onPrinted={onPrinted}
              disabled={regenerating}
            />
            {visit.fallback || visit.regen_pending ? regenerate : null}
          </div>
          <div className="d-visit-links">
            <ReportLink visitId={visit.id} />
            <PipelineLink visitId={visit.id} />
          </div>
        </div>
      );
    case "generating":
      return (
        <div className="d-visit-ops">
          <div className="d-actions">
            <Link className="d-linkbutton" to={`/doctor/pipeline/${visit.id}`}>
              変換の様子を見る
            </Link>
          </div>
        </div>
      );
    case "failed":
      return (
        <div className="d-visit-ops">
          <div className="d-actions">
            {visit.has_report ? (
              <>
                <span className="d-muted">{PREVIOUS_REPORT_NOTE}</span>
                <PrintActions
                  visit={visit}
                  onPrinted={onPrinted}
                  disabled={regenerating}
                />
              </>
            ) : (
              <span className="d-muted">レポートを作れませんでした</span>
            )}
            {regenerate}
          </div>
          <div className="d-visit-links">
            {visit.has_report ? <ReportLink visitId={visit.id} /> : null}
            <PipelineLink visitId={visit.id} />
          </div>
        </div>
      );
  }
}

/**
 * D3 の1行。受付番号・仮名ID・状態（主の状態のバッジと、副の注記「AI変換なし」・記録の追加）・受付・
 * 未処理（あれば橙の「要確認 N件」。0件なら何も出さない）・操作。
 * 一覧に出るのは generating・ready・failed だけ（印刷済み・期限切れは API が出さない）。
 * AI変換なしの ready と failed には「AI でもう一度変換」を出す（Claude の一時的な失敗の後）。
 * 自動の回数を使い切った後に記録が届いた ready にも出す（AI の結果でも）。
 * 変換し直しが failed で終わっても前のレポートは残るので、印刷・印刷済みにする・レポートを開くを出す。
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
          <RecordsAddedNotes visit={visit} />
        </span>
      </td>
      <td>{formatDay(visit.created_at)}</td>
      <td>
        {visit.unprocessed_count > 0 ? (
          <UnprocessedLink visitId={visit.id} count={visit.unprocessed_count} />
        ) : null}
      </td>
      <td className="d-visit-actions">
        <Actions
          visit={visit}
          onPrinted={onPrinted}
          onRegenerate={onRegenerate}
        />
      </td>
    </tr>
  );
}

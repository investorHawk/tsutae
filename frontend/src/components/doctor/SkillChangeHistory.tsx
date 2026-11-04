import type { SkillChange, SkillChangeStatus } from "../../api/types";
import { isUsableDiff } from "./diff";
import DiffView from "./DiffView";
import { formatDateTime } from "./format";
import { isWorking } from "./skillChangeWork";
import { isReportFormatSkill, skillDisplayName } from "./skillLabels";

const STATUS_LABELS: Readonly<Record<SkillChangeStatus, string>> = {
  pending: "承認待ち",
  approved: "承認",
  rejected: "却下",
  failed: "失敗",
};

/** 状態の表示。pending で diff がまだ無ければ「生成中」（承認待ちではない）。 */
function statusLabel(change: SkillChange): string {
  if (isWorking(change)) {
    return "生成中";
  }
  return STATUS_LABELS[change.status] ?? change.status;
}

function versionText(change: SkillChange): string {
  return change.status === "approved" && change.new_version !== null
    ? `${change.base_version} → ${change.new_version}`
    : String(change.base_version);
}

interface SkillChangeHistoryProps {
  changes: readonly SkillChange[];
  onReview: (change: SkillChange) => void;
}

/**
 * D4 の変更の履歴（新しい順で渡す）。承認待ちは「確認する」で差分を開ける（差分が空なら出さない）。
 * レジメン（T95 より前に一文で頼んだ regimen-*）の承認待ちは、承認しても反映できないので
 * 「確認する」を出さず、レジメンの画面へ案内する。
 */
export default function SkillChangeHistory({
  changes,
  onReview,
}: SkillChangeHistoryProps) {
  if (changes.length === 0) {
    return <p className="d-muted">変更の履歴はまだありません</p>;
  }
  return (
    <table className="d-table d-history" aria-label="変更の履歴">
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">依頼</th>
          <th scope="col">Skill</th>
          <th scope="col">一文</th>
          <th scope="col">状態</th>
          <th scope="col">version</th>
          <th scope="col">差分</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => (
          <tr key={change.id}>
            <td>#{change.id}</td>
            <td>{formatDateTime(change.created_at)}</td>
            <td>
              {skillDisplayName(change.skill_name)}
              <br />
              <code className="d-skill-code">{change.skill_name}</code>
            </td>
            <td>{change.requested_text}</td>
            <td>
              <span
                className={`d-change d-change--${isWorking(change) ? "working" : change.status}`}
              >
                {statusLabel(change)}
              </span>
              {change.error_code ? (
                <code className="d-change-code">{change.error_code}</code>
              ) : null}
            </td>
            <td>{versionText(change)}</td>
            <td>
              {change.status === "pending" &&
              isUsableDiff(change.diff) &&
              isReportFormatSkill(change.skill_name) ? (
                <button type="button" onClick={() => onReview(change)}>
                  確認する
                </button>
              ) : null}
              {change.status === "pending" &&
              !isReportFormatSkill(change.skill_name) ? (
                <p className="d-muted">
                  レジメンは「レジメン」のタブで直します（この依頼は反映できません）
                </p>
              ) : null}
              {change.diff ? (
                <details>
                  <summary>差分を見る</summary>
                  <DiffView diff={change.diff} label={`#${change.id} の差分`} />
                </details>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

import type { VisitStatus } from "../../api/types";

export const VISIT_STATUS_LABELS: Readonly<Record<VisitStatus, string>> = {
  generating: "生成中",
  ready: "印刷待ち",
  printed: "印刷済み",
  failed: "失敗",
};

/** 受診の状態（D3・D5）。色は doctor.css の .d-status--*。 */
export default function StatusBadge({ status }: { status: VisitStatus }) {
  return (
    <span className={`d-status d-status--${status}`}>
      {VISIT_STATUS_LABELS[status] ?? status}
    </span>
  );
}

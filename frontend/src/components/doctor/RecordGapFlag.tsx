import type { DoctorPatient } from "../../api/types";
import "./board.css";

type Gap = Pick<DoctorPatient, "record_stale" | "days_since_last_record">;

/**
 * 記録が途切れた患者の橙の印（判定は API の record_stale。今日を含めず3日前以前か、
 * 記録が1件も無い）。何日前かは API の days_since_last_record をそのまま出す。
 */
export default function RecordGapFlag({ gap }: { gap: Gap }) {
  if (!gap.record_stale) {
    return null;
  }
  if (gap.days_since_last_record === null) {
    return (
      <span className="d-flag" title="まだ記録が1件もありません">
        記録なし
      </span>
    );
  }
  return (
    <>
      <span
        className="d-flag"
        title="最後の記録が今日から3日以上前です（今日を含めない）"
      >
        3日以上記録なし
      </span>
      <span className="d-muted">{gap.days_since_last_record}日前</span>
    </>
  );
}

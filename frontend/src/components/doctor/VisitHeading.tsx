import type { VisitHeader } from "../../api/types";
import { formatDay } from "./dayLabel";

/** 「A-023 ・ P-DEMO0001 ・ 11月9日（月）18:16 受付」。受付番号が消えていれば出さない。 */
export function visitHeadingText(visit: VisitHeader): string {
  const parts = [
    ...(visit.reception_no !== null ? [visit.reception_no] : []),
    visit.patient_id,
    `${formatDay(visit.created_at)} 受付`,
  ];
  return parts.join(" ・ ");
}

/** 未処理・変換ログの見出しの受診（内部の受診の番号は出さない）。 */
export default function VisitHeading({ visit }: { visit: VisitHeader }) {
  return <span className="d-visit-heading">{visitHeadingText(visit)}</span>;
}

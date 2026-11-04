import type { PatientVisitDay } from "../../api/types";
import { usePatientStrings } from "../../strings/PatientStrings";
import { fillTemplate } from "../../strings/template";
import { formatDate } from "./history";

/**
 * 受診日の区切り（これまでの記録の一覧の中の1行）。左右に伸びる緑の線の中央に
 * 「受診日 11月9日（月）」（定型文 history.visit_day・history.date）。線は CSS の飾り
 * （::before・::after）で、読み上げは文字だけ。受付番号・状態は出さない（API にも無い）。
 * 一覧（ul）の中に置くので li。役割は既定の listitem のまま（separator にすると中の
 * 文字が名前にならず、日付が読まれないことがある）。
 */
export default function VisitDivider({ visit }: { visit: PatientVisitDay }) {
  const { t } = usePatientStrings();
  const date = formatDate(visit.visit_date, t) ?? visit.visit_date;
  return (
    <li className="p-visit-day">
      <time className="p-visit-day-label" dateTime={visit.visit_date}>
        {fillTemplate(t("history.visit_day"), { date })}
      </time>
    </li>
  );
}

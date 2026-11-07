import { NavLink } from "react-router-dom";
import { usePatientStrings } from "../../strings/PatientStrings";

/**
 * 患者画面の下のタブ（今日の記録／これまでの記録／受診／設定）。画面の下に固定する（patient.css）。
 * 今いる画面に aria-current="page" が付き、塗りで分かる。
 */
export default function PatientNav() {
  const { t } = usePatientStrings();
  return (
    <nav className="p-nav">
      <div className="p-nav-tabs">
        <NavLink to="/today">{t("nav.today")}</NavLink>
        <NavLink to="/history">{t("nav.history")}</NavLink>
        <NavLink to="/visit">{t("nav.visit")}</NavLink>
        <NavLink to="/settings">{t("nav.settings")}</NavLink>
      </div>
    </nav>
  );
}

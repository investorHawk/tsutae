import { NavLink } from "react-router-dom";
import { usePatientStrings } from "../../strings/PatientStrings";

/** 患者画面の下部ナビ（今日の記録／これまでの記録）。今いる画面に aria-current が付く。 */
export default function PatientNav() {
  const { t } = usePatientStrings();
  return (
    <nav className="p-nav">
      <NavLink to="/today">{t("nav.today")}</NavLink>
      <NavLink to="/history">{t("nav.history")}</NavLink>
    </nav>
  );
}

import { useState } from "react";
import NotifySettings from "../../components/patient/NotifySettings";
import NotRegistered from "../../components/patient/NotRegistered";
import PatientNav from "../../components/patient/PatientNav";
import { loadPid } from "../../patient/pid";
import { usePatientStrings } from "../../strings/PatientStrings";

/** P5 設定（/settings）。毎日のお知らせ。仮名ID が無ければ未登録の案内と番号の入力欄。 */
export default function Settings() {
  const { t } = usePatientStrings();
  const [pid] = useState(loadPid);
  return (
    <section className="page">
      <h1>{t("settings.title")}</h1>
      {pid ? <NotifySettings pid={pid} /> : <NotRegistered />}
      <PatientNav />
    </section>
  );
}

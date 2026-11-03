import { useState } from "react";
import HistoryList from "../../components/patient/HistoryList";
import { ErrorMessage } from "../../components/patient/Messages";
import PatientNav from "../../components/patient/PatientNav";
import { NOT_REGISTERED_KEY } from "../../components/patient/patientApi";
import { loadPid } from "../../patient/pid";
import { usePatientStrings } from "../../strings/PatientStrings";

/** P2 これまでの記録（/history）。読むだけ。仮名ID が無ければ未登録の案内だけ。 */
export default function History() {
  const { t } = usePatientStrings();
  const [pid] = useState(loadPid);
  return (
    <section className="page">
      <h1>{t("history.title")}</h1>
      {pid ? (
        <HistoryList pid={pid} />
      ) : (
        <ErrorMessage messageKey={NOT_REGISTERED_KEY} />
      )}
      <PatientNav />
    </section>
  );
}

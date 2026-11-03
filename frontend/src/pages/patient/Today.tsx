import { useState } from "react";
import { useLocation } from "react-router-dom";
import { DoneMessage, ErrorMessage } from "../../components/patient/Messages";
import PatientNav from "../../components/patient/PatientNav";
import { NOT_REGISTERED_KEY } from "../../components/patient/patientApi";
import TodayForm from "../../components/patient/TodayForm";
import { loadPid } from "../../patient/pid";
import { usePatientStrings } from "../../strings/PatientStrings";

function cameFromRegister(state: unknown): boolean {
  return (
    state !== null &&
    typeof state === "object" &&
    (state as { registered?: unknown }).registered === true
  );
}

/**
 * P1 今日の記録（/today）。仮名ID が無ければ未登録の案内だけ（API は呼ばない）。
 * 下部ナビの「今日の記録」を押すと（location.key が変わり）新しい記録を始める。
 */
export default function Today() {
  const { t } = usePatientStrings();
  const location = useLocation();
  const [pid] = useState(loadPid);
  return (
    <section className="page">
      <h1>{t("today.title")}</h1>
      {cameFromRegister(location.state) && (
        <DoneMessage messageKey="register.done" />
      )}
      {pid ? (
        <TodayForm key={location.key} pid={pid} />
      ) : (
        <ErrorMessage messageKey={NOT_REGISTERED_KEY} />
      )}
      <PatientNav />
    </section>
  );
}

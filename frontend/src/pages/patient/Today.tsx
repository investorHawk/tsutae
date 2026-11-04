import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();
  const [pid] = useState(loadPid);
  // 「登録しました」は登録の直後の1回だけ。履歴の state は消して、再読み込みでは出さない
  // 記録した後は消す（「登録しました」と「記録しました」を縦に並べない）
  const [justRegistered, setJustRegistered] = useState(() =>
    cameFromRegister(location.state),
  );
  useEffect(() => {
    if (cameFromRegister(location.state)) {
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, location.pathname, navigate]);
  return (
    <section className="page">
      <h1>{t("today.title")}</h1>
      {justRegistered && <DoneMessage messageKey="register.done" />}
      {pid ? (
        <TodayForm
          key={location.key}
          pid={pid}
          onSaved={() => setJustRegistered(false)}
        />
      ) : (
        <ErrorMessage messageKey={NOT_REGISTERED_KEY} />
      )}
      <PatientNav />
    </section>
  );
}

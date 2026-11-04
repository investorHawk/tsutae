import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { DoneMessage, ErrorMessage } from "../../components/patient/Messages";
import PatientNav from "../../components/patient/PatientNav";
import { formatDate } from "../../components/patient/history";
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
 * 見出し「今日の記録」と、その右の今日の日付（「11月9日（月）」）。日付はサーバーの今日
 * （GET questions の today）で、端末の時計は使わない。取れない間は出さない。
 * 日付は h1 の中に置き、読み上げは「今日の記録 11月9日（月）」と続けて読む。
 */
function TodayTitle({ today }: { today: string | null }) {
  const { t } = usePatientStrings();
  const date = today === null ? null : formatDate(today, t);
  return (
    <h1>
      {t("today.title")}
      {date !== null && (
        <>
          {" "}
          <span className="p-title-date">{date}</span>
        </>
      )}
    </h1>
  );
}

/**
 * P1 今日の記録（/today）。仮名ID が無ければ未登録の案内だけ（API は呼ばない）。
 * 下部ナビの「今日の記録」を押すと（location.key が変わり）新しい記録を始める。
 */
export default function Today() {
  const location = useLocation();
  const navigate = useNavigate();
  const [pid] = useState(loadPid);
  const [today, setToday] = useState<string | null>(null);
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
      <TodayTitle today={today} />
      {justRegistered && <DoneMessage messageKey="register.done" />}
      {pid ? (
        <TodayForm
          key={location.key}
          pid={pid}
          onSaved={() => setJustRegistered(false)}
          onToday={setToday}
        />
      ) : (
        <ErrorMessage messageKey={NOT_REGISTERED_KEY} />
      )}
      <PatientNav />
    </section>
  );
}

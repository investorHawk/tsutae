import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { DoneMessage } from "../../components/patient/Messages";
import NotifyBanner from "../../components/patient/NotifyBanner";
import NotRegistered from "../../components/patient/NotRegistered";
import PatientNav from "../../components/patient/PatientNav";
import { formatDate } from "../../components/patient/history";
import TodayForm from "../../components/patient/TodayForm";
import { useNewDayCheck } from "../../components/patient/useNewDayCheck";
import { loadPid } from "../../patient/pid";
import { clearDeliveredNotifications } from "../../patient/pushDevice";
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
 * P1 今日の記録（/today）。仮名ID が無ければ未登録の案内と番号の入力欄（記録の API は呼ばない）。
 * 下部ナビの「今日の記録」を押すと（location.key が変わり）新しい記録を始める。
 * 開いたまま日付が変わっていたら（useNewDayCheck）、前の日の完了の画面や書きかけを残さず読み直す
 * （前の日の入力を今日の記録として送らせない）。
 * 記録できたらバッジと表示中の通知を消す。通知の案内の帯は質問集を読めた後（登録済み）に、
 * 記録の欄の下へ出す（遅れて出ても「つらくて書けない」の位置を動かさない）。
 */
export default function Today() {
  const location = useLocation();
  const navigate = useNavigate();
  const [pid] = useState(loadPid);
  const [today, setToday] = useState<string | null>(null);
  const [dayRound, setDayRound] = useState(0);
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
  useNewDayCheck(pid, today, () => {
    setToday(null);
    setJustRegistered(false);
    setDayRound((n) => n + 1);
  });
  return (
    <section className="page">
      <TodayTitle today={today} />
      {justRegistered && <DoneMessage messageKey="register.done" />}
      {pid ? (
        <TodayForm
          key={`${location.key}:${dayRound}`}
          pid={pid}
          onSaved={() => {
            setJustRegistered(false);
            void clearDeliveredNotifications();
          }}
          onToday={setToday}
        />
      ) : (
        <NotRegistered />
      )}
      {pid && today !== null && <NotifyBanner />}
      <PatientNav />
    </section>
  );
}

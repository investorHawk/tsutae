import { useId } from "react";
import { isPushSupported } from "../../patient/pushDevice";
import { usePatientStrings } from "../../strings/PatientStrings";
import { LoadFailed, Loading } from "./LoadStatus";
import { DoneMessage, ErrorMessage } from "./Messages";
import NotRegistered from "./NotRegistered";
import { loadPushState, type PushState } from "./pushState";
import { NOTIFY_TIMES } from "./pushStatus";
import { SendingMessage } from "./TooSickButton";
import { useAsync } from "./useAsync";
import { usePushSettings, type PushSettings } from "./usePushSettings";

/** 使えないときの理由と次の操作の定型文（docs/plan-device-records.md §4.5）。 */
function Unavailable({ messageKey }: { messageKey: string }) {
  const { t } = usePatientStrings();
  return <p className="p-notice">{t(messageKey)}</p>;
}

/** 時刻（30 分刻み）。オフのあいだに選んだ時刻はオンにしたときに送る。 */
function TimeSelect({ push }: { push: PushSettings }) {
  const { t } = usePatientStrings();
  const id = useId();
  return (
    <>
      <label htmlFor={id}>{t("notify.time_label")}</label>
      <select
        id={id}
        value={push.notifyTime}
        disabled={push.busy}
        onChange={(e) => push.changeTime(e.target.value)}
      >
        {NOTIFY_TIMES.map((time) => (
          <option key={time} value={time}>
            {time}
          </option>
        ))}
      </select>
    </>
  );
}

function Feedback({ push }: { push: PushSettings }) {
  if (push.busy) {
    return <SendingMessage />;
  }
  if (push.feedback === null) {
    return null;
  }
  return push.feedback.kind === "done" ? (
    <DoneMessage messageKey={push.feedback.key} />
  ) : (
    <ErrorMessage messageKey={push.feedback.key} />
  );
}

function NotifyControls({ pid, state }: { pid: string; state: PushState }) {
  const { t } = usePatientStrings();
  const push = usePushSettings(pid, state);
  if (push.notRegistered) {
    return <NotRegistered />;
  }
  if (push.status === "no_key") {
    return <Unavailable messageKey="notify.no_key" />;
  }
  if (push.status === "denied") {
    return <Unavailable messageKey="notify.denied" />;
  }
  const on = push.status === "on";
  return (
    <>
      <p className="p-notify-status" role="status">
        {t(on ? "notify.status_on" : "notify.status_off")}
      </p>
      <TimeSelect push={push} />
      <Feedback push={push} />
      {on ? (
        <>
          <button
            type="button"
            className="p-button--primary"
            disabled={push.busy}
            onClick={push.sendTest}
          >
            {t("notify.test")}
          </button>
          <button type="button" disabled={push.busy} onClick={push.disable}>
            {t("notify.turn_off")}
          </button>
        </>
      ) : (
        <button
          type="button"
          className="p-button--primary"
          disabled={push.busy}
          onClick={push.enable}
        >
          {t("notify.turn_on")}
        </button>
      )}
    </>
  );
}

function NotifyLoader({ pid }: { pid: string }) {
  const loaded = useAsync(loadPushState, pid);
  if (loaded.status === "loading") {
    return <Loading />;
  }
  if (loaded.status === "error") {
    return <LoadFailed onReload={loaded.reload} />;
  }
  return <NotifyControls pid={pid} state={loaded.data} />;
}

/** 設定の「毎日のお知らせ」。未対応の端末は API を呼ばずに案内だけ出す。 */
export default function NotifySettings({ pid }: { pid: string }) {
  const { t } = usePatientStrings();
  return (
    <>
      <h2>{t("notify.section_title")}</h2>
      <p>{t("notify.about")}</p>
      {isPushSupported() ? (
        <NotifyLoader pid={pid} />
      ) : (
        <Unavailable messageKey="notify.unsupported" />
      )}
    </>
  );
}

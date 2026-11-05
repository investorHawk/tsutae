import { useId, useState, type FormEvent } from "react";
import { isApiError } from "../../api/http";
import { DoneMessage, ErrorMessage } from "../../components/patient/Messages";
import NotRegistered from "../../components/patient/NotRegistered";
import PatientNav from "../../components/patient/PatientNav";
import {
  GENERIC_ERROR_KEY,
  isNotRegistered,
} from "../../components/patient/patientApi";
import { normalizeReceptionNo } from "../../components/patient/reception";
import { loadPid } from "../../patient/pid";
import { sendVisit } from "../../patient/visitEntries";
import { usePatientStrings } from "../../strings/PatientStrings";

type Phase = "editing" | "sending" | "done" | "not_registered";

const INVALID_KEY = "visit.invalid";
/** 今コースが無い（409 no_course）。受付で声をかけてもらう。 */
const NO_COURSE_KEY = "visit.no_course";
const REGISTERED_KEY = "register.done";
/** 受付番号は送る前にサーバーと同じ検査をしているので、422・413 は記録が断られたとき（§5.5）。 */
const RECORDS_REJECTED_KEY = "visit.records_rejected";

function errorKeyOf(err: unknown): string {
  if (isApiError(err) && err.status === 400) {
    return INVALID_KEY;
  }
  if (isApiError(err) && (err.status === 422 || err.status === 413)) {
    return RECORDS_REJECTED_KEY;
  }
  if (isApiError(err) && err.status === 409 && err.code === "no_course") {
    return NO_COURSE_KEY;
  }
  return GENERIC_ERROR_KEY;
}

/**
 * P3 受診（/visit。下の受診タブ）。送ると何が起きるか（visit.about）と番号の例
 * （visit.example）を出し、受付番号と範囲内の端末の記録を送り（§5.5）、届いたら visit.done
 * だけを出す。送る範囲を聞くのに仮名ID が要るので、無ければ番号の入力欄を出す。
 * native の maxLength は UTF-16 単位で数え貼り付けを黙って切るので付けない。
 * 長さは送る前に normalizeReceptionNo（code point で 1〜32 字）で検査する。
 * 送って 401/403 なら番号の入力欄を出す。登録できたら受付番号を残したまま送る前に戻す
 * （登録した番号で送り直すので、読み直さない）。
 */
export default function Visit() {
  const { t } = usePatientStrings();
  const inputId = useId();
  const exampleId = useId();
  const [pid, setPid] = useState(loadPid);
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<Phase>(
    pid === null ? "not_registered" : "editing",
  );
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [registered, setRegistered] = useState(false);

  function resumeAfterRegister(newPid: string) {
    setPid(newPid);
    setRegistered(true);
    setPhase("editing");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (pid === null) {
      setPhase("not_registered");
      return;
    }
    const receptionNo = normalizeReceptionNo(text);
    if (receptionNo === null) {
      setErrorKey(INVALID_KEY);
      return;
    }
    setPhase("sending");
    setErrorKey(null);
    setRegistered(false);
    try {
      await sendVisit(pid, receptionNo);
      setPhase("done");
    } catch (err) {
      if (isNotRegistered(err)) {
        setPhase("not_registered");
        return;
      }
      setErrorKey(errorKeyOf(err));
      setPhase("editing");
    }
  }

  if (phase === "done") {
    return (
      <section className="page">
        <h1>{t("visit.title")}</h1>
        <DoneMessage messageKey="visit.done" />
        <PatientNav />
      </section>
    );
  }

  return (
    <section className="page">
      <h1>{t("visit.title")}</h1>
      {phase === "not_registered" ? (
        <NotRegistered onRegistered={resumeAfterRegister} />
      ) : (
        <form onSubmit={handleSubmit} noValidate>
          {registered && <DoneMessage messageKey={REGISTERED_KEY} />}
          <p>{t("visit.about")}</p>
          <label htmlFor={inputId}>{t("visit.reception_label")}</label>
          <p id={exampleId} className="p-hint">
            {t("visit.example")}
          </p>
          <input
            id={inputId}
            aria-describedby={exampleId}
            type="text"
            autoComplete="off"
            autoCapitalize="characters"
            placeholder={t("visit.reception_placeholder")}
            value={text}
            disabled={phase === "sending"}
            onChange={(e) => setText(e.target.value)}
          />
          {errorKey && <ErrorMessage messageKey={errorKey} />}
          <button
            type="submit"
            className="p-button--primary"
            disabled={phase === "sending"}
          >
            {t("visit.submit")}
          </button>
        </form>
      )}
      <PatientNav />
    </section>
  );
}

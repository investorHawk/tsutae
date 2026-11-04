import { useId, useState, type FormEvent } from "react";
import { isApiError } from "../../api/http";
import { submitVisit } from "../../api/patient";
import { DoneMessage, ErrorMessage } from "../../components/patient/Messages";
import PatientNav from "../../components/patient/PatientNav";
import {
  GENERIC_ERROR_KEY,
  NOT_REGISTERED_KEY,
  isNotRegistered,
} from "../../components/patient/patientApi";
import { normalizeReceptionNo } from "../../components/patient/reception";
import { usePatientStrings } from "../../strings/PatientStrings";

type Phase = "editing" | "sending" | "done" | "not_registered";

const INVALID_KEY = "visit.invalid";
/** 今コースが無い（409 no_course）。受付で声をかけてもらう。 */
const NO_COURSE_KEY = "visit.no_course";

function errorKeyOf(err: unknown): string {
  if (isApiError(err) && (err.status === 400 || err.status === 422)) {
    return INVALID_KEY;
  }
  if (isApiError(err) && err.status === 409 && err.code === "no_course") {
    return NO_COURSE_KEY;
  }
  return GENERIC_ERROR_KEY;
}

/**
 * P3 受診時（/visit。院内QRで開く）。受付番号を送り、届いたら visit.done だけを出す。
 * 患者は Cookie で識別される（経路に仮名ID を入れない）。
 * native の maxLength は UTF-16 単位で数え貼り付けを黙って切るので付けない。
 * 長さは送る前に normalizeReceptionNo（code point で 1〜32 字）で検査する。
 */
export default function Visit() {
  const { t } = usePatientStrings();
  const inputId = useId();
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<Phase>("editing");
  const [errorKey, setErrorKey] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const receptionNo = normalizeReceptionNo(text);
    if (receptionNo === null) {
      setErrorKey(INVALID_KEY);
      return;
    }
    setPhase("sending");
    setErrorKey(null);
    try {
      await submitVisit(receptionNo);
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
        <ErrorMessage messageKey={NOT_REGISTERED_KEY} />
      ) : (
        <form onSubmit={handleSubmit} noValidate>
          <label htmlFor={inputId}>{t("visit.reception_label")}</label>
          <input
            id={inputId}
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

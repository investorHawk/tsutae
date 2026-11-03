import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { isApiError } from "../../api/http";
import { registerPatient } from "../../api/patient";
import { ErrorMessage } from "../../components/patient/Messages";
import { GENERIC_ERROR_KEY } from "../../components/patient/patientApi";
import { isValidPid, loadPid, restorePid, savePid } from "../../patient/pid";
import { usePatientStrings } from "../../strings/PatientStrings";

const REQUIRED_KEY = "register.required";
const INVALID_KEY = "register.invalid";

/** URL の pid の問題（無い・形式が違う）。問題が無ければ null。 */
function pidProblem(pid: string): string | null {
  if (pid === "") {
    return REQUIRED_KEY;
  }
  return isValidPid(pid) ? null : INVALID_KEY;
}

function errorKeyOf(err: unknown): string {
  if (isApiError(err) && [400, 404, 422].includes(err.status)) {
    return INVALID_KEY;
  }
  return GENERIC_ERROR_KEY;
}

/**
 * P0 登録（/register?pid=...。院内で渡された登録用QR）。
 * ボタンでスマホに仮名ID を保存 → POST register（失敗なら保存を戻す）→ /today。パスワードなし。
 */
export default function Register() {
  const { t } = usePatientStrings();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const pid = (params.get("pid") ?? "").trim();
  const [sending, setSending] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const problem =
    pidProblem(pid) ?? (errorKey === INVALID_KEY ? INVALID_KEY : null);

  async function handleRegister() {
    // 先に仮名ID を保存する。保存できないまま登録すると Cookie だけ残り、P1・P2 は
    // 未登録の案内になる。登録が失敗したら、前に保存していた値に戻す
    const previous = loadPid();
    try {
      savePid(pid);
    } catch {
      setErrorKey(GENERIC_ERROR_KEY);
      return;
    }
    setSending(true);
    setErrorKey(null);
    try {
      await registerPatient(pid);
      navigate("/today", { replace: true, state: { registered: true } });
    } catch (err) {
      restorePid(previous);
      setErrorKey(errorKeyOf(err));
      setSending(false);
    }
  }

  return (
    <section className="page">
      <h1>{t("register.title")}</h1>
      <p className="p-synthetic">{t("app.notice_synthetic")}</p>
      {problem ? (
        <ErrorMessage messageKey={problem} />
      ) : (
        <>
          {errorKey && <ErrorMessage messageKey={errorKey} />}
          <button
            type="button"
            className="p-button--primary"
            disabled={sending}
            onClick={handleRegister}
          >
            {t("register.button")}
          </button>
        </>
      )}
    </section>
  );
}

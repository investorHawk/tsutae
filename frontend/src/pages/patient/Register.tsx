import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { registerPatient } from "../../api/patient";
import { ErrorMessage } from "../../components/patient/Messages";
import {
  GENERIC_ERROR_KEY,
  registerErrorKeyOf,
} from "../../components/patient/patientApi";
import { resendSubscription } from "../../components/patient/pushResend";
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
      // この端末の通知が前の患者の判定で動き続けないよう、今の番号の登録にする
      void resendSubscription();
      navigate("/today", { replace: true, state: { registered: true } });
    } catch (err) {
      restorePid(previous);
      setErrorKey(registerErrorKeyOf(err, INVALID_KEY));
      setSending(false);
    }
  }

  return (
    <section className="page">
      <h1>{t("register.title")}</h1>
      {/* 1文ずつ別の行にする（スマホ幅で読みやすいように） */}
      <p className="p-about">{t("register.about_record")}</p>
      <p className="p-about">{t("register.about_doctor")}</p>
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

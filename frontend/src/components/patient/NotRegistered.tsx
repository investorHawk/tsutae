import { useId, useState, type FormEvent } from "react";
import { registerPatient } from "../../api/patient";
import {
  isValidPid,
  loadPid,
  normalizePidInput,
  restorePid,
  savePid,
} from "../../patient/pid";
import { reloadPage } from "../../patient/reload";
import { usePatientStrings } from "../../strings/PatientStrings";
import { ErrorMessage } from "./Messages";
import { resendSubscription } from "./pushResend";
import {
  GENERIC_ERROR_KEY,
  NOT_REGISTERED_KEY,
  registerErrorKeyOf,
} from "./patientApi";

const INVALID_KEY = "register.number_invalid";

/**
 * 順は P0 登録と同じ: 前の値を読む → 保存 → POST register → 失敗なら戻す。
 * 保存できないまま登録すると Cookie だけ残るので、保存が先。失敗の定型文のキーを返す
 * （成功は null）。
 */
async function saveAndRegister(pid: string): Promise<string | null> {
  const previous = loadPid();
  try {
    savePid(pid);
  } catch {
    return GENERIC_ERROR_KEY;
  }
  try {
    await registerPatient(pid);
    // この端末の通知が前の患者の判定で動き続けないよう、今の番号の登録にする
    void resendSubscription();
    return null;
  } catch (err) {
    restorePid(previous);
    return registerErrorKeyOf(err, INVALID_KEY);
  }
}

/**
 * 未登録の案内と、病院で渡された番号（仮名ID）の入力欄。iPhone のホーム画面アプリは
 * Safari と Cookie・localStorage が別で QR の登録が引き継がれないので、ここで登録する。
 * 成功したら onRegistered（既定は読み直し）。形が違う番号は API を呼ばない。
 * native の maxLength は貼り付けを黙って切るので付けない。
 */
export default function NotRegistered({
  onRegistered = reloadPage,
}: {
  /** 登録できた。入力を残して続ける画面だけ渡す（引数は保存した仮名ID） */
  onRegistered?: (pid: string) => void;
}) {
  const { t } = usePatientStrings();
  const inputId = useId();
  const errorId = useId();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const pid = normalizePidInput(text);
    if (!isValidPid(pid)) {
      setErrorKey(INVALID_KEY);
      return;
    }
    setSending(true);
    setErrorKey(null);
    const failedKey = await saveAndRegister(pid);
    if (failedKey !== null) {
      setErrorKey(failedKey);
      setSending(false);
      return;
    }
    // 読み直しが終わるまで押せないままにする
    onRegistered(pid);
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <ErrorMessage messageKey={NOT_REGISTERED_KEY} />
      <label htmlFor={inputId}>{t("register.number_label")}</label>
      <input
        id={inputId}
        className="p-number-input"
        type="text"
        autoComplete="off"
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        placeholder={t("register.number_placeholder")}
        value={text}
        disabled={sending}
        aria-invalid={errorKey === INVALID_KEY ? true : undefined}
        aria-describedby={errorKey ? errorId : undefined}
        onChange={(e) => setText(e.target.value)}
      />
      {errorKey && <ErrorMessage id={errorId} messageKey={errorKey} />}
      <button type="submit" className="p-button--primary" disabled={sending}>
        {t("register.number_submit")}
      </button>
    </form>
  );
}

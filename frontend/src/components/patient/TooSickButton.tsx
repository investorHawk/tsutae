import { usePatientStrings } from "../../strings/PatientStrings";
import { ErrorMessage } from "./Messages";

interface TooSickButtonProps {
  /** 入力済みのときの確認（today.too_sick_confirm と はい／やめる）を出している */
  confirming: boolean;
  disabled: boolean;
  sending: boolean;
  /** このボタンの送信の失敗（定型文のキー）。ボタンの直後に出す */
  errorKey: string | null;
  onPress: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * 段階0「今日はつらくて書けない」。確認・送信中・失敗の知らせはこのボタンの直後に出す
 * （画面の下の方に出すと、つらい日に気づけない）。
 */
export default function TooSickButton({
  confirming,
  disabled,
  sending,
  errorKey,
  onPress,
  onConfirm,
  onCancel,
}: TooSickButtonProps) {
  const { t } = usePatientStrings();
  return (
    <div className="p-too-sick">
      <button
        type="button"
        className="p-button--too-sick"
        disabled={disabled || confirming}
        onClick={onPress}
      >
        {t("today.too_sick_button")}
      </button>
      {confirming && (
        <div className="p-confirm">
          <p>{t("today.too_sick_confirm")}</p>
          <button
            type="button"
            className="p-button--primary"
            disabled={disabled}
            onClick={onConfirm}
          >
            {t("today.too_sick_confirm_yes")}
          </button>
          <button type="button" disabled={disabled} onClick={onCancel}>
            {t("today.too_sick_confirm_no")}
          </button>
        </div>
      )}
      {sending && <SendingMessage />}
      {errorKey && <ErrorMessage messageKey={errorKey} />}
    </div>
  );
}

/** 送信中の知らせ（today.sending）。 */
export function SendingMessage() {
  const { t } = usePatientStrings();
  return (
    <p className="p-sending" role="status">
      {t("today.sending")}
    </p>
  );
}

import { useCallback, useId, useRef, useState } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";
import { fillTemplate } from "../../strings/template";
import { ErrorMessage } from "./Messages";
import { useCountdown } from "./useCountdown";
import type { ConfirmMode } from "./useTooSickConfirm";

/** 何も入れていない時、確認を出してから自動で「はい」を押すまでの秒数。 */
export const AUTO_CONFIRM_SECONDS = 3;

interface TooSickButtonProps {
  /** 確認を出している（auto: 3秒で自動、manual: 入力を捨てる確認）。出していなければ null */
  confirming: ConfirmMode | null;
  disabled: boolean;
  sending: boolean;
  /** このボタンの送信の失敗（定型文のキー）。ボタンの直後に出す */
  errorKey: string | null;
  onPress: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}

interface ConfirmProps {
  id: string;
  mode: ConfirmMode;
  disabled: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * 確認の枠。auto では残り秒数（role=status）と、地が左から満ちる「はい」を出し、
 * 時間がたつと「はい」を押す。「はい」は1回の確認で1回だけ（押すのとタイマーが重ならない）。
 * 枠が消える（やめる・送信開始・画面を離れる）とタイマーも止まる。
 */
function TooSickConfirm({
  id,
  mode,
  disabled,
  onConfirm,
  onCancel,
}: ConfirmProps) {
  const { t } = usePatientStrings();
  const fired = useRef(false);
  // 「はい」「やめる」を押したら、親が枠を閉じるのを待たずにタイマーを止める
  const [stopped, setStopped] = useState(false);
  const confirmOnce = useCallback(() => {
    setStopped(true);
    if (!fired.current) {
      fired.current = true;
      onConfirm();
    }
  }, [onConfirm]);
  const cancel = () => {
    setStopped(true);
    onCancel();
  };
  const auto = mode === "auto" && !disabled && !stopped;
  const left = useCountdown(auto, AUTO_CONFIRM_SECONDS, confirmOnce);
  const yesLabel = t("today.too_sick_confirm_yes");
  return (
    <div id={id} className="p-confirm">
      <p>
        {t(
          mode === "auto"
            ? "today.too_sick_confirm_empty"
            : "today.too_sick_confirm",
        )}
      </p>
      {auto && (
        <p className="p-countdown" role="status">
          {fillTemplate(t("today.too_sick_countdown"), { seconds: left })}
        </p>
      )}
      <button
        type="button"
        className={`p-button--primary p-confirm-yes${auto ? " p-confirm-yes--auto" : ""}`}
        disabled={disabled}
        onClick={confirmOnce}
      >
        <span className="p-confirm-yes-label">{yesLabel}</span>
        {auto && (
          <span
            className="p-countdown-fill"
            aria-hidden="true"
            style={{ animationDuration: `${AUTO_CONFIRM_SECONDS}s` }}
          >
            {yesLabel}
          </span>
        )}
      </button>
      <button type="button" disabled={disabled} onClick={cancel}>
        {t("today.too_sick_confirm_no")}
      </button>
    </div>
  );
}

/**
 * 段階0「今日はつらくて書けない」。押すと必ず確認を出す（入力が無ければ3秒で自動で記録）。
 * 確認・送信中・失敗の知らせはこのボタンの直後に出す（画面の下の方に出すと、つらい日に
 * 気づけない）。確認を出している間、このボタンは押された見た目（aria-expanded）。
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
  const confirmId = useId();
  return (
    <div className="p-too-sick">
      <button
        type="button"
        className="p-button--too-sick"
        disabled={disabled}
        aria-expanded={confirming !== null}
        aria-controls={confirming !== null ? confirmId : undefined}
        onClick={confirming === null ? onPress : undefined}
      >
        {t("today.too_sick_button")}
      </button>
      {confirming !== null && (
        <TooSickConfirm
          id={confirmId}
          mode={confirming}
          disabled={disabled}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
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

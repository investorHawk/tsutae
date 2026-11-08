import { usePatientStrings } from "../../strings/PatientStrings";

function NumberCard({ labelKey, pid }: { labelKey: string; pid: string }) {
  const { t } = usePatientStrings();
  return (
    <div className="p-guide-number">
      <p className="p-guide-number-label">{t(labelKey)}</p>
      <p className="p-guide-number-value">{pid}</p>
    </div>
  );
}

/**
 * 別の番号が入っているスマホで登録用QRを開いたときの確認。家族のQRや人から届いたリンクで、
 * 記録の行き先と通知が黙って別の番号に替わらないようにする。迷ったときの安全な側
 * （切り替えない）を先に大きく出す。
 */
export default function PidSwitchConfirm({
  current,
  next,
  sending,
  onConfirm,
  onCancel,
}: {
  current: string;
  next: string;
  sending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = usePatientStrings();
  return (
    <div className="p-confirm">
      <p>{t("register.switch_notice")}</p>
      <NumberCard labelKey="register.switch_current_label" pid={current} />
      <NumberCard labelKey="register.switch_new_label" pid={next} />
      <p>{t("register.switch_about")}</p>
      <button
        type="button"
        className="p-button--primary"
        disabled={sending}
        onClick={onCancel}
      >
        {t("register.switch_cancel")}
      </button>
      <button type="button" disabled={sending} onClick={onConfirm}>
        {t("register.switch_confirm")}
      </button>
    </div>
  );
}

import { useRef, useState } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";
import { resetDevice } from "./resetDevice";
import { ErrorMessage } from "./Messages";

type Step = "idle" | "first" | "second" | "running" | "partial";

function ConfirmFirst({
  onNext,
  onCancel,
}: {
  onNext: () => void;
  onCancel: () => void;
}) {
  const { t } = usePatientStrings();
  return (
    <div className="p-confirm">
      <p>{t("device_reset.confirm_first")}</p>
      <button type="button" className="p-button--primary" onClick={onNext}>
        {t("device_reset.confirm_first_yes")}
      </button>
      <button type="button" onClick={onCancel}>
        {t("device_reset.cancel")}
      </button>
    </div>
  );
}

/** 「次へ」の同じ位置に「やめる」を置く（二度押しで消さないように）。 */
function ConfirmSecond({
  onYes,
  onCancel,
}: {
  onYes: () => void;
  onCancel: () => void;
}) {
  const { t } = usePatientStrings();
  return (
    <div className="p-confirm">
      <p>{t("device_reset.confirm_second")}</p>
      <button type="button" onClick={onCancel}>
        {t("device_reset.cancel")}
      </button>
      <button type="button" className="p-button--primary" onClick={onYes}>
        {t("device_reset.confirm_second_yes")}
      </button>
    </div>
  );
}

/**
 * 設定の「このスマホの登録と記録を消す」（docs/plan-device-records.md §5.9）。
 * 2段階の確認を画面の中に出す（window.confirm は使わない）。
 * 消しきれなかったものがあれば知らせて、確認なしで押し直せる。全て消せたら onCleared。
 */
export default function DeviceReset({
  pid,
  onStart,
  onCleared,
}: {
  pid: string;
  /** 消し始めた（他の操作を隠す） */
  onStart: () => void;
  onCleared: () => void;
}) {
  const { t } = usePatientStrings();
  const [step, setStep] = useState<Step>("idle");
  const sentEndpoint = useRef<string | null>(null);

  async function run() {
    setStep("running");
    onStart();
    const { cleared, endpoint } = await resetDevice(pid, sentEndpoint.current);
    sentEndpoint.current = endpoint;
    if (cleared) {
      onCleared();
    } else {
      setStep("partial");
    }
  }

  return (
    <>
      <h2>{t("device_reset.title")}</h2>
      <p>{t("device_reset.about")}</p>
      <p>{t("device_reset.icon_note")}</p>
      {step === "idle" && (
        <button type="button" onClick={() => setStep("first")}>
          {t("device_reset.button")}
        </button>
      )}
      {step === "first" && (
        <ConfirmFirst
          onNext={() => setStep("second")}
          onCancel={() => setStep("idle")}
        />
      )}
      {step === "second" && (
        <ConfirmSecond onYes={run} onCancel={() => setStep("idle")} />
      )}
      {step === "running" && (
        <p className="p-sending" role="status">
          {t("device_reset.running")}
        </p>
      )}
      {step === "partial" && (
        <>
          <ErrorMessage messageKey="device_reset.partial" />
          <button type="button" onClick={run}>
            {t("device_reset.retry")}
          </button>
        </>
      )}
    </>
  );
}

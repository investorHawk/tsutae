import { useEffect, useRef, useState } from "react";

interface TwoStepButtonProps {
  label: string;
  /** 2段目に出す確認の文 */
  prompt: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** 2段目の押下で呼ぶ。失敗の表示は呼び出し側で行う */
  onConfirm: () => Promise<void> | void;
  disabled?: boolean;
}

type Step = "idle" | "confirm" | "busy";

/**
 * 2段階のボタン（window.confirm を使わない画面内の確認）。
 * 1回目で確認の文と「実行／やめる」を出し、2回目で実行する。
 */
export default function TwoStepButton({
  label,
  prompt,
  confirmLabel,
  cancelLabel = "やめる",
  onConfirm,
  disabled = false,
}: TwoStepButtonProps) {
  const [step, setStep] = useState<Step>("idle");
  const mounted = useRef(true);
  const confirmRef = useRef<HTMLButtonElement>(null);

  // 2段目に進んだら確認のボタンへ（押したボタンは消えるので、focus を失わせない）
  useEffect(() => {
    if (step === "confirm") {
      confirmRef.current?.focus();
    }
  }, [step]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function confirm() {
    setStep("busy");
    try {
      await onConfirm();
    } catch (err) {
      console.error("操作に失敗しました", err);
    } finally {
      if (mounted.current) {
        setStep("idle");
      }
    }
  }

  if (step === "idle") {
    return (
      <button
        type="button"
        disabled={disabled}
        onClick={() => setStep("confirm")}
      >
        {label}
      </button>
    );
  }

  const busy = step === "busy";
  return (
    <span className="d-twostep" role="group" aria-label={label}>
      <span className="d-twostep-prompt">{prompt}</span>
      <button
        ref={confirmRef}
        type="button"
        className="d-danger"
        disabled={busy}
        onClick={() => void confirm()}
      >
        {confirmLabel}
      </button>
      <button type="button" disabled={busy} onClick={() => setStep("idle")}>
        {cancelLabel}
      </button>
    </span>
  );
}

import { useId } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";
import type { TemperatureProblem } from "./entryForm";
import { ErrorMessage } from "./Messages";

/** 体温の問題ごとの定型文のキー（数字でない／30〜45 の外）。 */
const PROBLEM_KEYS: Readonly<Record<TemperatureProblem, string>> = {
  invalid: "temperature.invalid",
  out_of_range: "temperature.out_of_range",
};

interface TemperatureFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** 送ろうとして不正だったときの問題。正しければ null */
  problem: TemperatureProblem | null;
  disabled?: boolean;
}

/** 体温の数値入力（「測った」のときだけ出す）。検証は entryForm.temperatureProblem。 */
export default function TemperatureField({
  value,
  onChange,
  problem,
  disabled = false,
}: TemperatureFieldProps) {
  const invalid = problem !== null;
  const { t } = usePatientStrings();
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <div>
      <label htmlFor={id}>{t("temperature.label")}</label>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        maxLength={8}
        value={value}
        disabled={disabled}
        aria-invalid={invalid}
        aria-describedby={invalid ? errorId : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {problem !== null && (
        <ErrorMessage id={errorId} messageKey={PROBLEM_KEYS[problem]} />
      )}
    </div>
  );
}

import { useId } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";
import { ErrorMessage } from "./Messages";

interface TemperatureFieldProps {
  value: string;
  onChange: (value: string) => void;
  invalid: boolean;
  disabled?: boolean;
}

/** 体温の数値入力（「測った」のときだけ出す）。検証は entryForm.parseTemperature。 */
export default function TemperatureField({
  value,
  onChange,
  invalid,
  disabled = false,
}: TemperatureFieldProps) {
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
      {invalid && (
        <ErrorMessage id={errorId} messageKey="temperature.invalid" />
      )}
    </div>
  );
}

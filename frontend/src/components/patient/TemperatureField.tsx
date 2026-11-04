import { useEffect, useId, useRef } from "react";
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
  /**
   * 現れた時に入力欄へ focus する（「測った」を押した直後。スマホで数字のキーパッドが
   * 出る）。初めから「測った」が入っている時（取り消して戻った時）は false
   */
  focusOnShow?: boolean;
}

/**
 * 体温の数値入力（「測った」のときだけ出す）。「体温 [ 36.8 ] ℃」を1行に並べる。
 * type="text" と inputMode="decimal"（type=number は使わない）。検証は
 * entryForm.temperatureProblem。単位と失敗の文は aria-describedby で入力欄に結ぶ。
 */
export default function TemperatureField({
  value,
  onChange,
  problem,
  disabled = false,
  focusOnShow = false,
}: TemperatureFieldProps) {
  const invalid = problem !== null;
  const { t } = usePatientStrings();
  const id = useId();
  const unitId = `${id}-unit`;
  const errorId = `${id}-error`;
  const inputRef = useRef<HTMLInputElement>(null);
  const focusAtFirst = useRef(focusOnShow);

  useEffect(() => {
    if (focusAtFirst.current) {
      inputRef.current?.focus();
    }
  }, []);

  return (
    <div>
      <div className="p-temperature">
        <label htmlFor={id}>{t("temperature.label")}</label>
        <input
          ref={inputRef}
          id={id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          maxLength={8}
          value={value}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={invalid ? `${unitId} ${errorId}` : unitId}
          onChange={(e) => onChange(e.target.value)}
        />
        <span id={unitId} className="p-temperature-unit">
          {t("temperature.unit")}
        </span>
      </div>
      {problem !== null && (
        <ErrorMessage id={errorId} messageKey={PROBLEM_KEYS[problem]} />
      )}
    </div>
  );
}

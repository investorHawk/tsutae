import { useId } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";

interface FreeTextFieldProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/**
 * 段階2 の自由記載。原文をそのまま送る（前後の空白だけ落とす）。
 * native の maxLength は UTF-16 単位で数え、絵文字などを含む契約上有効な 2000 字を
 * 入れられず貼り付けも黙って切るので付けない。長さは送る前に entryForm.buildEntry で検査する。
 */
export default function FreeTextField({
  value,
  onChange,
  disabled = false,
}: FreeTextFieldProps) {
  const { t } = usePatientStrings();
  const id = useId();
  return (
    <div>
      <label htmlFor={id}>{t("today.free_text_label")}</label>
      <textarea
        id={id}
        rows={5}
        placeholder={t("today.free_text_placeholder")}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

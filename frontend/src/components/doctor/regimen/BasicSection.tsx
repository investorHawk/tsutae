import { FieldInput } from "./FieldInput";
import FormSection from "./FormSection";
import { BASIC_LABELS } from "./fieldLabels";
import { parseWholeNumber, type Parsed } from "./fieldValues";
import { useRegimenForm } from "./formContext";

const asText = (text: string): Parsed<string | null> => ({
  ok: true,
  value: text.trim() === "" ? null : text.trim(),
});

/** 基本: レジメン名・識別名（新規の下書きだけ）・対象（任意）・1コースの日数。 */
export default function BasicSection() {
  const { draft } = useRegimenForm();
  const { basic } = draft.form;
  const existing = draft.base_version !== null;
  return (
    <FormSection section="basic" title="基本">
      <div className="rf-grid">
        <FieldInput
          fieldId="basic.display_name"
          label={BASIC_LABELS.display_name}
          value={basic.display_name ?? ""}
          parse={asText}
          placeholder="例: FOLFIRI＋BV"
        />
        <FieldInput
          fieldId="basic.code"
          label={`${BASIC_LABELS.code}（英大文字・数字・-）`}
          value={basic.code ?? ""}
          parse={asText}
          placeholder="例: FOLFIRI-BV"
          disabled={existing}
        />
        <FieldInput
          fieldId="basic.target"
          label={`${BASIC_LABELS.target}（任意）`}
          value={basic.target ?? ""}
          parse={asText}
          placeholder="例: 大腸がん"
        />
        <FieldInput
          fieldId="basic.cycle_days"
          label={`${BASIC_LABELS.cycle_days}（7〜42）`}
          value={basic.cycle_days === null ? "" : String(basic.cycle_days)}
          parse={parseWholeNumber}
          inputMode="numeric"
          placeholder="例: 14"
          disabled={draft.schedule_locked}
        />
      </div>
      {existing ? (
        <p className="d-muted rf-hint">
          識別名（{basic.code}）は既存のレジメンでは変えられません。
        </p>
      ) : null}
    </FormSection>
  );
}

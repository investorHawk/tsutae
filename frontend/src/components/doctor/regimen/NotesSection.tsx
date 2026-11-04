import { FieldInput } from "./FieldInput";
import FormSection from "./FormSection";
import { useRegimenForm } from "./formContext";

/** 補足の指示（自由記載・任意）。空でなければ SKILL.md の最後の節に描く。 */
export default function NotesSection() {
  const { draft } = useRegimenForm();
  return (
    <FormSection section="notes" title="補足の指示（任意）">
      <FieldInput
        fieldId="notes"
        label="型に入らない施設の決まり（例: 内服の期間は人ごとに違う）"
        value={draft.form.notes}
        parse={(text) => ({ ok: true, value: text })}
        multiline
      />
    </FormSection>
  );
}

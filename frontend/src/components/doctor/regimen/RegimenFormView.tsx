import { useMemo, useState } from "react";
import type { LibraryQuestion } from "../../../api/types";
import BasicSection from "./BasicSection";
import DrugsSection from "./DrugsSection";
import LibraryDialog from "./LibraryDialog";
import NotesSection from "./NotesSection";
import QuestionsSection from "./QuestionsSection";
import SideEffectsSection from "./SideEffectsSection";
import { useRegimenForm } from "./formContext";
import { newRowId } from "./rowIds";

interface RegimenFormViewProps {
  handleError: (err: unknown) => string;
}

/**
 * 左のフォーム（5節）。応答中は fieldset ごと止める（欄・行の操作・部品集）。
 * 部品集の小窓から選んだ質問は、行の追加と値を1回の PATCH で足す。
 */
export default function RegimenFormView({ handleError }: RegimenFormViewProps) {
  const { draft, locked, patch } = useRegimenForm();
  const [opener, setOpener] = useState<HTMLButtonElement | null>(null);
  const usedKeys = useMemo(
    () =>
      new Set(
        draft.form.questions.flatMap((q) => (q.key === null ? [] : [q.key])),
      ),
    [draft.form.questions],
  );

  function closeLibrary() {
    opener?.focus();
    setOpener(null);
  }

  function pick(question: LibraryQuestion) {
    const rowId = newRowId(draft.form, "questions");
    const base = `questions.${rowId}`;
    return patch({
      adds: [{ section: "questions", row_id: rowId }],
      changes: [
        { field_id: `${base}.key`, value: question.key },
        { field_id: `${base}.label`, value: question.label },
        { field_id: `${base}.text`, value: question.text },
        { field_id: `${base}.answer_type`, value: question.answer_type },
      ],
    });
  }

  return (
    <>
      <fieldset className="rf-form" disabled={locked} aria-busy={locked}>
        <legend className="rf-sr-only">レジメンのフォーム</legend>
        <BasicSection />
        <DrugsSection />
        <SideEffectsSection />
        <QuestionsSection onOpenLibrary={setOpener} />
        <NotesSection />
      </fieldset>
      {opener ? (
        <LibraryDialog
          usedKeys={usedKeys}
          handleError={handleError}
          onPick={pick}
          onClose={closeLibrary}
        />
      ) : null}
    </>
  );
}

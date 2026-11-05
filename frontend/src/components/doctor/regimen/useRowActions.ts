import { useCallback, useRef, useState } from "react";
import type { FieldChange, RowSection } from "../../../api/regimenTypes";
import { domIdOf, sectionDomId } from "./fieldLabels";
import { useRegimenForm } from "./formContext";
import { newRowId } from "./rowIds";

/** 行の最初の欄（足した後・消した後に focus を移す先）。 */
const FIRST_FIELD: Readonly<Record<RowSection, string>> = {
  drugs: "name",
  side_effects: "phrases",
  questions: "label",
};

/** 描き直しの後に、欄（無ければ節の見出し）へ focus を移す。 */
function focusLater(domId: string, fallbackId: string): void {
  window.setTimeout(() => {
    (
      document.getElementById(domId) ?? document.getElementById(fallbackId)
    )?.focus();
  }, 0);
}

/**
 * 行の追加と削除（PATCH の adds・deletes）。行の追加は値の変更と同じ1回で送れる
 * （backend は削除 → 追加 → 欄の変更 の順に当てる）。足している間は adding で
 * ボタンを止める（二度押しで同じ row_id を2回送らない）。行の単位の理由
 * （`drugs.<row_id>`）は節の見出しの下に出る。
 */
export function useRowActions() {
  const { draft, patch } = useRegimenForm();
  const [adding, setAdding] = useState(false);
  const addingRef = useRef(false);

  const addRow = useCallback(
    async (
      section: RowSection,
      firstField: string,
      values: Readonly<Record<string, unknown>> = {},
    ) => {
      if (addingRef.current) {
        return false;
      }
      addingRef.current = true;
      setAdding(true);
      const rowId = newRowId(draft.form, section);
      const changes: FieldChange[] = Object.entries(values).map(
        ([name, value]) => ({ field_id: `${section}.${rowId}.${name}`, value }),
      );
      try {
        const ok = await patch(
          { adds: [{ section, row_id: rowId }], changes },
          [section, `${section}.${rowId}`],
        );
        if (ok) {
          focusLater(
            domIdOf(`${section}.${rowId}.${firstField}`),
            sectionDomId(section),
          );
        }
        return ok;
      } finally {
        addingRef.current = false;
        setAdding(false);
      }
    },
    [draft.form, patch],
  );

  const deleteRow = useCallback(
    async (section: RowSection, rowId: string) => {
      const rows: readonly { row_id: string }[] = draft.form[section];
      const index = rows.findIndex((r) => r.row_id === rowId);
      const next = rows[index + 1] ?? rows[index - 1];
      const ok = await patch({ deletes: [`${section}.${rowId}`] }, [
        section,
        `${section}.${rowId}`,
      ]);
      if (ok) {
        // 消したボタンは無くなるので、次の行（無ければ前の行・節の見出し）へ
        focusLater(
          next
            ? domIdOf(`${section}.${next.row_id}.${FIRST_FIELD[section]}`)
            : sectionDomId(section),
          sectionDomId(section),
        );
      }
      return ok;
    },
    [draft.form, patch],
  );

  return { addRow, deleteRow, adding };
}

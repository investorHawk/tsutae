import type { SideEffectRow } from "../../../api/regimenTypes";
import { FieldInput, FieldSelect } from "./FieldInput";
import FormSection from "./FormSection";
import { formatList, parseList, type Parsed } from "./fieldValues";
import { useRegimenForm } from "./formContext";
import { useRowActions } from "./useRowActions";

const asList = (text: string): Parsed<string[]> => ({
  ok: true,
  value: parseList(text),
});

function SideEffectRowView({ row }: { row: SideEffectRow }) {
  const { draft, locked } = useRegimenForm();
  const { deleteRow } = useRowActions();
  const base = `side_effects.${row.row_id}`;
  const name = row.phrases[0] ?? "名前のない症状";
  const options = [
    { value: "", label: "なし" },
    ...draft.form.questions
      .filter((q) => q.key)
      .map((q) => ({ value: q.key ?? "", label: q.label ?? q.key ?? "" })),
  ];
  return (
    <tr>
      <td>
        <FieldInput
          fieldId={`${base}.phrases`}
          label={`患者の言い方の例（${name}）`}
          hideLabel
          value={formatList(row.phrases)}
          parse={asList}
          placeholder="例: 下痢、お腹がゆるい"
        />
      </td>
      <td>
        <FieldInput
          fieldId={`${base}.ctcae_terms`}
          label={`CTCAE の用語（${name}）`}
          hideLabel
          value={formatList(row.ctcae_terms)}
          parse={asList}
          placeholder="例: 下痢"
        />
      </td>
      <td>
        <FieldSelect
          fieldId={`${base}.question_key`}
          label={`対応する質問（${name}）`}
          hideLabel
          value={row.question_key ?? ""}
          options={options}
          toValue={(v) => (v === "" ? null : v)}
        />
      </td>
      <td>
        <button
          type="button"
          className="rf-row-delete"
          disabled={locked}
          aria-label={`${name} の行を消す`}
          onClick={() => void deleteRow("side_effects", row.row_id)}
        >
          消す
        </button>
      </td>
    </tr>
  );
}

/** 副作用（注意する症状）: 患者の言い方・CTCAE の用語・対応する質問。 */
export default function SideEffectsSection() {
  const { draft, locked } = useRegimenForm();
  const { addRow, adding } = useRowActions();
  const rows = draft.form.side_effects;
  return (
    <FormSection
      section="side_effects"
      title="副作用（注意する症状）"
      actions={
        <button
          type="button"
          disabled={locked || adding}
          onClick={() => void addRow("side_effects", "phrases")}
        >
          ＋ 症状を足す
        </button>
      }
    >
      <p className="d-muted rf-hint">
        言い方・用語は「、」で区切って複数入れられます。用語は CTCAE v5.0
        JCOG版の一覧にある語だけ（一覧に無い語は欄の下に理由が出ます）。
      </p>
      {rows.length > 0 ? (
        <div className="rf-table-wrap">
          <table className="rf-table">
            <thead>
              <tr>
                <th scope="col">患者の言い方の例</th>
                <th scope="col">CTCAE の用語</th>
                <th scope="col">対応する質問</th>
                <th scope="col">
                  <span className="rf-sr-only">行の操作</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <SideEffectRowView key={row.row_id} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </FormSection>
  );
}

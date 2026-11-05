import type { DrugRow, Route } from "../../../api/regimenTypes";
import DayBar, { ROUTE_LABELS } from "./DayBar";
import { FieldInput, FieldSelect } from "./FieldInput";
import FormSection from "./FormSection";
import {
  formatDays,
  parseDays,
  parseWholeNumber,
  type Parsed,
} from "./fieldValues";
import { useRegimenForm } from "./formContext";
import { useRowActions } from "./useRowActions";

const ROUTE_OPTIONS = [
  { value: "", label: "選ぶ" },
  ...(Object.keys(ROUTE_LABELS) as Route[]).map((route) => ({
    value: route,
    label: ROUTE_LABELS[route],
  })),
];

/** 薬の名前の候補の datalist（節に1つ。全ての行の名前の欄が同じものを指す）。 */
const DRUG_NAMES_LIST_ID = "rf-drug-names";

const asText = (text: string): Parsed<string | null> => ({
  ok: true,
  value: text.trim() === "" ? null : text.trim(),
});

function DrugRowView({ drug }: { drug: DrugRow }) {
  const { draft, locked, drugNames } = useRegimenForm();
  const { deleteRow } = useRowActions();
  const base = `drugs.${drug.row_id}`;
  const oral = drug.route === "oral";
  const scheduleLocked = draft.schedule_locked;
  const name = drug.name ?? "名前のない薬";
  return (
    <tr>
      <td>
        <FieldInput
          fieldId={`${base}.name`}
          label={`薬の名前（${name}）`}
          hideLabel
          value={drug.name ?? ""}
          parse={asText}
          placeholder="例: オキサリプラチン"
          list={drugNames.length > 0 ? DRUG_NAMES_LIST_ID : undefined}
        />
      </td>
      <td>
        <FieldSelect
          fieldId={`${base}.route`}
          label={`経路（${name}）`}
          hideLabel
          value={drug.route ?? ""}
          options={ROUTE_OPTIONS}
          toValue={(v) => (v === "" ? null : v)}
          disabled={scheduleLocked}
        />
      </td>
      <td>
        <FieldInput
          fieldId={`${base}.days`}
          label={`Day（${name}）`}
          hideLabel
          value={formatDays(drug.days)}
          parse={parseDays}
          placeholder="Day1・8・15"
          disabled={scheduleLocked}
        />
      </td>
      <td>
        <FieldInput
          fieldId={`${base}.times_per_day`}
          label={`内服の回数（${name}）`}
          hideLabel
          value={drug.times_per_day === null ? "" : String(drug.times_per_day)}
          parse={parseWholeNumber}
          inputMode="numeric"
          placeholder={oral ? "1日の回数（例: 2）" : "—"}
          disabled={!oral && drug.times_per_day === null}
        />
      </td>
      <td>
        <FieldInput
          fieldId={`${base}.start_note`}
          label={`飲み始め（${name}）`}
          hideLabel
          value={drug.start_note ?? ""}
          parse={asText}
          placeholder={oral ? "例: Day1 の夕方から" : "—"}
          disabled={!oral && drug.start_note === null}
        />
      </td>
      <td>
        <button
          type="button"
          className="rf-row-delete"
          disabled={locked || scheduleLocked}
          aria-label={`${name} の行を消す`}
          onClick={() => void deleteRow("drugs", drug.row_id)}
        >
          消す
        </button>
      </td>
    </tr>
  );
}

/** 投与スケジュール: 薬ごとに 名前・経路・Day の範囲（複数）・内服の回数・飲み始め＋Day の帯。 */
export default function DrugsSection() {
  const { draft, locked, drugNames } = useRegimenForm();
  const { addRow, adding } = useRowActions();
  const { drugs } = draft.form;
  return (
    <FormSection
      section="drugs"
      title="投与スケジュール（内服・注射）"
      actions={
        <button
          type="button"
          disabled={locked || adding || draft.schedule_locked}
          onClick={() => void addRow("drugs", "name")}
        >
          ＋ 薬を足す
        </button>
      }
    >
      {draft.schedule_locked ? (
        <p className="rf-locked-note">
          このレジメンには患者がいるため、1コースの日数・薬の経路と
          Day・ポンプ抜去日は変えられません
          （変えるときは新しいレジメンとして作ります）。薬の名前と内服の補足は直せます。
        </p>
      ) : null}
      {drugs.length > 0 ? (
        <>
          {drugNames.length > 0 ? (
            <datalist id={DRUG_NAMES_LIST_ID}>
              {drugNames.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          ) : null}
          <div className="rf-table-wrap">
            <table className="rf-table">
              <thead>
                <tr>
                  <th scope="col">薬</th>
                  <th scope="col">経路</th>
                  <th scope="col">Day</th>
                  <th scope="col">内服の回数（1日）</th>
                  <th scope="col">飲み始め（内服）</th>
                  <th scope="col">
                    <span className="rf-sr-only">行の操作</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {drugs.map((drug) => (
                  <DrugRowView key={drug.row_id} drug={drug} />
                ))}
              </tbody>
            </table>
          </div>
          <DayBar cycleDays={draft.form.basic.cycle_days} drugs={drugs} />
        </>
      ) : null}
    </FormSection>
  );
}

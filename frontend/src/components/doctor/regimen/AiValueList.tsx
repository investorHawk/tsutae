import type { AiValue } from "../../../api/regimenTypes";
import { formatDays, formatList } from "./fieldValues";

const SOURCE_LABELS: Readonly<Record<AiValue["source"], string>> = {
  standard: "標準の値",
  doctor_text: "先生の文から",
};

/** 値を1行の文字にする（Day の範囲・一覧・数）。 */
export function valueText(value: unknown): string {
  if (Array.isArray(value)) {
    if (value.every((v) => typeof v === "string")) {
      return formatList(value as string[]);
    }
    if (
      value.every(
        (v) =>
          typeof v === "object" && v !== null && "start" in v && "end" in v,
      )
    ) {
      return formatDays(value as { start: number; end: number }[]);
    }
  }
  if (value === null || value === undefined || value === "") {
    return "（空）";
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

interface AiValueListProps {
  values: readonly AiValue[];
  confirmed: boolean;
  disabled: boolean;
  onToggle: (value: boolean) => void;
  onDelete: (fieldId: string) => void;
}

/** 確認: AI が入れた値の一覧（行ごとに「削除」）とチェック1回。 */
export default function AiValueList({
  values,
  confirmed,
  disabled,
  onToggle,
  onDelete,
}: AiValueListProps) {
  return (
    <section className="rf-section rf-ai-list" aria-labelledby="rf-ai-h">
      <h3 id="rf-ai-h" tabIndex={-1}>
        AI が入れた値（{values.length}{" "}
        件）。採用の前に確かめてください（要らない値は削除できます）
      </h3>
      <table className="rf-table">
        <thead>
          <tr>
            <th scope="col">欄</th>
            <th scope="col">値</th>
            <th scope="col">出どころ</th>
            <th scope="col">
              <span className="rf-sr-only">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {values.map((v) => (
            <tr key={v.field_id}>
              <td>{v.label}</td>
              <td>{valueText(v.value)}</td>
              <td>{SOURCE_LABELS[v.source]}</td>
              <td>
                <button
                  type="button"
                  className="rf-row-delete"
                  disabled={disabled}
                  aria-label={`${v.label} の値を削除`}
                  onClick={() => onDelete(v.field_id)}
                >
                  削除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <label className="rf-check">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={disabled}
          onChange={(e) => onToggle(e.target.checked)}
        />
        上の値を全て確かめました
      </label>
    </section>
  );
}

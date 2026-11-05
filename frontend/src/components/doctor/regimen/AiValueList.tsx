import type { AiValue } from "../../../api/regimenTypes";
import { aiRowsOf, type AiRow, type QuestionLabels } from "./aiRows";

interface AiValueListProps {
  values: readonly AiValue[];
  /** 対応する質問の欄を短い名前で出すための、今のフォームの質問 */
  questions: QuestionLabels;
  confirmed: boolean;
  disabled: boolean;
  onToggle: (value: boolean) => void;
  onDelete: (row: AiRow) => void;
}

/** 確認: AI が入れた値（標準の値）の一覧（行ごとに「削除」）とチェック1回。 */
export default function AiValueList({
  values,
  questions,
  confirmed,
  disabled,
  onToggle,
  onDelete,
}: AiValueListProps) {
  const rows = aiRowsOf(values, questions);
  return (
    <section className="rf-section rf-ai-list" aria-labelledby="rf-ai-h">
      <h3 id="rf-ai-h" tabIndex={-1}>
        AI が入れた値（{rows.length}{" "}
        件）。先生の文に無かったので、標準の値から入れました（要らない行は削除できます）
      </h3>
      <table className="rf-table">
        <thead>
          <tr>
            <th scope="col">欄</th>
            <th scope="col">値</th>
            <th scope="col">
              <span className="rf-sr-only">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>{row.where}</td>
              <td>{row.text}</td>
              <td>
                <button
                  type="button"
                  className="rf-row-delete"
                  disabled={disabled}
                  aria-label={`${row.where} の値を削除`}
                  onClick={() => onDelete(row)}
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

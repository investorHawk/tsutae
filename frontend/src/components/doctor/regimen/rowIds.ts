/**
 * 画面が足す行の row_id（backend の ROW_ID_PATTERN `^[a-z0-9][a-z0-9_-]{0,31}$`）。
 *
 * - Claude が足す行の `drug<N>`・`effect<N>`・`question<N>` と重ねない（T94）
 * - 数字3桁以上で終わる形を避ける（H1 の id_like に掛かる形。row_id は依頼文に出さないが
 *   念のため）。番号は英小文字（a, b, …, z, ba, …）で振る
 */
import type { RegimenFormValues, RowSection } from "../../../api/regimenTypes";

const PREFIX: Readonly<Record<RowSection, string>> = {
  drugs: "drug-add-",
  side_effects: "effect-add-",
  questions: "question-add-",
};

function letters(n: number): string {
  let rest = n;
  let out = "";
  do {
    out = String.fromCharCode(97 + (rest % 26)) + out;
    rest = Math.floor(rest / 26);
  } while (rest > 0);
  return out;
}

/** その節でまだ使っていない row_id（a から順に）。 */
export function newRowId(form: RegimenFormValues, section: RowSection): string {
  const used = new Set(form[section].map((row) => row.row_id));
  for (let n = 0; ; n += 1) {
    const id = `${PREFIX[section]}${letters(n)}`;
    if (!used.has(id)) {
      return id;
    }
  }
}

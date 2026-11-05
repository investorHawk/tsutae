/** チャットの薬の候補の札（純関数）。 */
import type { RegimenDraft } from "../../../api/regimenTypes";

/** 末尾がこれなら「・」を足さない（文の区切り・つなぎ・開き括弧・空白と改行）。 */
const ENDS_WITH_SEPARATOR = /[・、，,。．.:：;；/／＋+（(「\s]$/u;

/**
 * 入力欄の文の末尾に薬の名前を足した文。空でなければ「・」でつなぐ（末尾が既に区切りなら
 * つながない）。上限を超えるなら元の文のまま（途中で切れた名前を入れない）。
 */
export function appendDrugName(
  text: string,
  name: string,
  max: number,
): string {
  const joiner = text === "" || ENDS_WITH_SEPARATOR.test(text) ? "" : "・";
  const next = `${text}${joiner}${name}`;
  return next.length > max ? text : next;
}

/**
 * 札を出すか。新しいレジメンの最初の文のためだけに出す（会話が始まれば Claude の問いと選択肢
 * が主になるので、入力欄の周りを空ける。既存のレジメンは薬が既にある）。
 */
export function showsDrugChips(
  draft: Pick<RegimenDraft, "base_version"> & { chat: readonly unknown[] },
  names: readonly string[],
): boolean {
  return (
    draft.base_version === null && draft.chat.length === 0 && names.length > 0
  );
}

/**
 * 自由記載を端末に保存する形に直す。記録はスマホに置くので、記録のときにサーバーの検査を通らない。
 * 受付（schemas.py EntryCreate）が断る形や、kind が変わる形で保存すると、その1件のせいで受診の
 * 全体が 422 になる（plan-device-records §5.5）。同じ表（src/test/fixtures/free_text_cases.json）を
 * backend のテストも読む。
 */

/** Python の str.strip が落とす空白（JS の trim とは U+FEFF と U+001C〜1F・U+0085 が違う）。 */
export const PYTHON_SPACE =
  "\\t-\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";

/** 前後から落とす文字。U+FEFF は Python では残るが、今までどおり画面では空として扱う。 */
const EDGE = `[${PYTHON_SPACE}\\ufeff]+`;
const EDGE_SPACE = new RegExp(`^${EDGE}|${EDGE}$`, "g");
/** 片割れのサロゲート。受付の検査が文字列として読めずに断る。見た目は文字にならないので黙って落とす。 */
const LONE_SURROGATE = /\p{Cs}/gu;

export function cleanFreeText(text: string): string {
  return text.replace(LONE_SURROGATE, "").replace(EDGE_SPACE, "");
}

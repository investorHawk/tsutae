import { PYTHON_SPACE } from "../../patient/freeText";

/**
 * 受付番号（P3）。バックエンド（docs/architecture.md §8b api/visit.py）と同じ検査で、NFKC の
 * 後に前後の空白を落とし、1〜32 字（Python と同じく code point で数える）で、制御文字・書式文字
 * （Cc・Cf。貼り付けで混じる U+200B や絵文字の ZWJ）を含まないものだけを通す。日本語を含む番号も
 * 契約上有効。大文字化・記号の置き換えもしない（サーバーが保存する値と画面で送る値を変えないため）。
 * 同じ表（src/test/fixtures/reception_no_cases.json）を backend のテストも読む。
 */
export const RECEPTION_NO_MAX = 32;

const EDGE_SPACE = new RegExp(`^[${PYTHON_SPACE}]+|[${PYTHON_SPACE}]+$`, "g");
const CONTROL_OR_FORMAT = /[\p{Cc}\p{Cf}]/u;

export function normalizeReceptionNo(input: string): string | null {
  const value = input.normalize("NFKC").replace(EDGE_SPACE, "");
  const length = [...value].length;
  if (length < 1 || length > RECEPTION_NO_MAX) {
    return null;
  }
  return CONTROL_OR_FORMAT.test(value) ? null : value;
}

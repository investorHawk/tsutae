/**
 * 受付番号（P3）。バックエンド（docs/architecture.md §8b api/visit.py）と同じく、
 * NFKC の後に前後の空白を落とし、1〜32 字（Python と同じく code point で数える）だけを通す。
 * 文字の種類は制限しない（日本語を含む番号も契約上有効）。大文字化・記号の置き換えもしない
 * （サーバーが保存する値と画面で送る値を変えないため）。
 */
export const RECEPTION_NO_MAX = 32;

export function normalizeReceptionNo(input: string): string | null {
  const value = input.normalize("NFKC").trim();
  const length = [...value].length;
  return length >= 1 && length <= RECEPTION_NO_MAX ? value : null;
}

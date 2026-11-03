/**
 * API の本文（外から来た値）の実行時検査の部品（docs/architecture.md §9 W2b の決定）。
 * 成功の本文が契約と違えば invalid_response の ApiError にし、画面は失敗として出す（黙って空にしない）。
 */
import { ApiError, INVALID_RESPONSE } from "./http";

export type Item = Record<string, unknown>;

export function isRecord(value: unknown): value is Item {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export const isString = (v: unknown): v is string => typeof v === "string";
export const isInt = (v: unknown): v is number => Number.isInteger(v);
export const isBool = (v: unknown): v is boolean => typeof v === "boolean";
/** null・省略を許す文字列。 */
export const isOptString = (v: unknown): boolean =>
  v === undefined || v === null || isString(v);
/** null・省略を許す整数。 */
export const isOptInt = (v: unknown): boolean =>
  v === undefined || v === null || isInt(v);
/** null・省略を許す数（NaN・Infinity は JSON に無い）。 */
export const isOptNumber = (v: unknown): boolean =>
  v === undefined || v === null || typeof v === "number";

/** 1 以上の整数。 */
export const isPositiveInt = (v: unknown): v is number => isInt(v) && v >= 1;

/** "YYYY-MM-DD"（§2 の日付の形）。 */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
export const isIsoDate = (v: unknown): v is string =>
  isString(v) && ISO_DATE.test(v);
/** null・省略を許す "YYYY-MM-DD"。 */
export const isOptIsoDate = (v: unknown): boolean =>
  v === undefined || v === null || isIsoDate(v);

/** 文字数（Python の len と同じく code point で数える。UTF-16 の単位ではない）。 */
export function codePointLength(text: string): number {
  return [...text].length;
}

export const oneOf =
  <T extends string>(values: readonly T[]) =>
  (v: unknown): v is T =>
    values.some((value) => value === v);

/** 配列で、全要素がオブジェクトで isItem に合う。 */
export const everyItem =
  (isItem: (item: Item) => boolean) =>
  (v: unknown): boolean =>
    Array.isArray(v) && v.every((item) => isRecord(item) && isItem(item));

/** 成功の本文が契約（types.ts）と違う。画面は「0件」ではなく失敗として出す。 */
export function invalidResponse(): ApiError {
  return new ApiError(200, INVALID_RESPONSE);
}

/**
 * 本文の body[key] の配列を返す。key が無い・配列でない・要素がオブジェクトでない・
 * isItem に合わない要素があれば invalid_response の ApiError を投げる（黙って空にしない）。
 */
export function listOf<T>(
  body: unknown,
  key: string,
  isItem: (item: Item) => boolean = () => true,
): T[] {
  const value = isRecord(body) ? body[key] : undefined;
  if (!Array.isArray(value)) {
    throw invalidResponse();
  }
  const ok = value.every((item) => isRecord(item) && isItem(item));
  if (!ok) {
    throw invalidResponse();
  }
  return [...value] as T[];
}

/** body が isBody に合えば T として返し、合わなければ invalid_response を投げる。 */
export function checked<T>(body: unknown, isBody: (b: Item) => boolean): T {
  if (!isRecord(body) || !isBody(body)) {
    throw invalidResponse();
  }
  return body as T;
}

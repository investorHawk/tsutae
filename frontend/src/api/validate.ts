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

/** 項目が存在する（値が null でもよい。省略は不正）。 */
export function has(v: Item, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(v, key);
}

/** 型の `T | null`（? なし）: 項目は必須、値は null か isValue に合うもの。 */
export const hasNullable =
  (key: string, isValue: (x: unknown) => boolean) =>
  (v: Item): boolean =>
    has(v, key) && (v[key] === null || isValue(v[key]));

/** 年月日が暦に実在する（2026-02-30・13月を落とす）。 */
function isCalendarDate(year: number, month: number, day: number): boolean {
  const d = new Date(Date.UTC(year, month - 1, day));
  return (
    d.getUTCFullYear() === year &&
    d.getUTCMonth() === month - 1 &&
    d.getUTCDate() === day
  );
}

/** "YYYY-MM-DD"（§2 の日付の形）で、暦に実在する日。 */
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
export const isIsoDate = (v: unknown): v is string => {
  const m = isString(v) ? ISO_DATE.exec(v) : null;
  return m !== null && isCalendarDate(Number(m[1]), Number(m[2]), Number(m[3]));
};

/**
 * ISO 8601 の日時（§2: +09:00 付き。Python の isoformat の形で、秒は必須・小数秒は6桁まで）。
 * 日付は暦に実在し、時刻は 00:00:00〜23:59:59。
 */
const ISO_DATE_TIME =
  /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?\+09:00$/;
export const isIsoDateTime = (v: unknown): v is string => {
  const m = isString(v) ? ISO_DATE_TIME.exec(v) : null;
  return (
    m !== null &&
    isIsoDate(m[1]) &&
    Number(m[2]) < 24 &&
    Number(m[3]) < 60 &&
    Number(m[4]) < 60
  );
};
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

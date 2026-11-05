/**
 * D4 レジメンの欄の値と入力の文字の行き来（純関数）。PATCH .../fields は型に厳しい
 * （1コースの日数は数・Day は {start, end} の一覧・言い方は文字の一覧）ので、画面の
 * 入力はここで値に直してから送る。読めない入力は送らずに欄の下へ理由を出す。
 */
import type { DayRange } from "../../../api/regimenTypes";

export type Parsed<T> = { ok: true; value: T } | { ok: false; message: string };

const LIST_FIELDS = new Set(["days", "phrases", "ctcae_terms"]);
const RANGE_SEP = /[〜~\-–—ー－]/;
const PART_SEP = /[・,、，\s]+/;

function normalize(text: string): string {
  return text.normalize("NFKC").trim();
}

function parsePart(part: string): DayRange | null {
  const pieces = part.split(RANGE_SEP);
  if (pieces.length > 2 || pieces.some((p) => !/^[0-9]+$/.test(p))) {
    return null;
  }
  const start = Number(pieces[0]);
  const end = Number(pieces[pieces.length - 1]);
  return start >= 1 && end >= start ? { start, end } : null;
}

/** 「Day1・8・15」「Day1〜5・8〜12」「1-3」→ DayRange[]。空は []。 */
export function parseDays(text: string): Parsed<DayRange[]> {
  const body = normalize(text).replace(/day/gi, " ").trim();
  if (body === "") {
    return normalize(text) === ""
      ? { ok: true, value: [] }
      : { ok: false, message: "Day の数字を入れてください（例: Day1・8・15）" };
  }
  const parts = body.split(PART_SEP).filter((p) => p !== "");
  const ranges: DayRange[] = [];
  for (const part of parts) {
    const range = parsePart(part.replace(/\s+/g, ""));
    if (!range) {
      return {
        ok: false,
        message: "Day は「Day1・8・15」「Day1〜5・8〜12」の形で入れてください",
      };
    }
    ranges.push(range);
  }
  return { ok: true, value: ranges };
}

/** DayRange[] → 「Day1〜5・8〜12」。 */
export function formatDays(ranges: readonly DayRange[]): string {
  if (ranges.length === 0) {
    return "";
  }
  const parts = ranges.map((r) =>
    r.start === r.end ? `${r.start}` : `${r.start}〜${r.end}`,
  );
  return `Day${parts.join("・")}`;
}

/** 「、」「,」「/」・改行で区切った一覧（前後の空白と空の項目を落とす）。 */
export function parseList(text: string): string[] {
  return text
    .split(/[、,，/／\n]/)
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

export function formatList(items: readonly string[]): string {
  return items.join("、");
}

/** 整数の欄（1コースの日数・内服の回数）。空は null。 */
export function parseWholeNumber(text: string): Parsed<number | null> {
  const body = normalize(text);
  if (body === "") {
    return { ok: true, value: null };
  }
  if (!/^[0-9]+$/.test(body)) {
    return { ok: false, message: "整数で入れてください" };
  }
  return { ok: true, value: Number(body) };
}

/** 値を1行の文字にする（Day の範囲・一覧・数。確認の画面の一覧）。 */
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
      return formatDays(value as DayRange[]);
    }
  }
  if (value === null || value === undefined || value === "") {
    return "（空）";
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** 欄を空にする値（一覧の欄は []・補足の指示は ""・ほかは null）。 */
export function emptyValueOf(fieldId: string): unknown {
  if (fieldId === "notes") {
    return "";
  }
  const name = fieldId.split(".").pop() ?? "";
  return LIST_FIELDS.has(name) ? [] : null;
}

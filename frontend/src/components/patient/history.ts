/** 自分の記録（P2）の並べ方と日時の出し方。文字は数字と記号だけ（定型文は t() で）。 */
import type { PatientEntry } from "../../api/types";
import { fillTemplate } from "../../strings/template";

const TIME_PATTERN = /T(\d{2}):(\d{2})/;
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function timeOf(entry: PatientEntry): number {
  const ms = Date.parse(entry.recorded_at);
  return Number.isNaN(ms) ? 0 : ms;
}

/** 記録日時の新しい順（同じなら id の大きい順）に並べた新しい配列。 */
export function newestFirst(entries: readonly PatientEntry[]): PatientEntry[] {
  return [...entries].sort((a, b) => timeOf(b) - timeOf(a) || b.id - a.id);
}

/** 日付（YYYY-MM-DD）の月・日・曜日。 */
export interface DateParts {
  month: number;
  day: number;
  /** 0 = 日曜 … 6 = 土曜（定型文 weekday.0〜weekday.6） */
  weekday: number;
}

export interface RecordedAtParts extends DateParts {
  /** "8:10"（時の先頭の 0 なし）。読めなければ null */
  time: string | null;
}

type RecordedAt = Pick<PatientEntry, "recorded_at" | "record_date">;

/**
 * 暦に実在する YYYY-MM-DD の月・日・曜日。曜日は端末の時差によらず日付から決める。
 * 読めなければ null。
 */
export function dateParts(value: string): DateParts | null {
  const date = DATE_PATTERN.exec(value);
  if (!date) {
    return null;
  }
  const [year, month, day] = [
    Number(date[1]),
    Number(date[2]),
    Number(date[3]),
  ];
  const utc = new Date(Date.UTC(year, month - 1, day));
  if (utc.getUTCMonth() !== month - 1 || utc.getUTCDate() !== day) {
    return null;
  }
  return { month, day, weekday: utc.getUTCDay() };
}

/**
 * 記録日（record_date。JST の日付）の月・日・曜日と、記録した時の表記（+09:00）のままの
 * 時:分。記録日が読めなければ null。
 */
export function recordedAtParts(entry: RecordedAt): RecordedAtParts | null {
  const parts = dateParts(entry.record_date);
  if (parts === null) {
    return null;
  }
  const time = TIME_PATTERN.exec(entry.recorded_at);
  return {
    ...parts,
    time: time ? `${Number(time[1])}:${time[2]}` : null,
  };
}

function fillDate(parts: DateParts, t: (key: string) => string): string {
  return fillTemplate(t("history.date"), {
    month: parts.month,
    day: parts.day,
    weekday: t(`weekday.${parts.weekday}`),
  });
}

/**
 * 「11月9日（月）」の形（定型文 history.date と weekday.*）。今日の記録の見出しの
 * 日付（サーバーの今日）に使う。読めなければ null（出さない）。
 */
export function formatDate(
  value: string,
  t: (key: string) => string,
): string | null {
  const parts = dateParts(value);
  return parts === null ? null : fillDate(parts, t);
}

/**
 * 「11月9日（月）13:47」の形（定型文 history.date と weekday.*）。時刻が読めなければ
 * 日付だけ、記録日が読めなければ record_date の文字のまま。
 */
export function formatRecordedAt(
  entry: RecordedAt,
  t: (key: string) => string,
): string {
  const parts = recordedAtParts(entry);
  if (parts === null) {
    return entry.record_date;
  }
  const date = fillDate(parts, t);
  return parts.time === null ? date : `${date}${parts.time}`;
}

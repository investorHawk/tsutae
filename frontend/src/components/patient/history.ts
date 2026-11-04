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

export interface RecordedAtParts {
  month: number;
  day: number;
  /** 0 = 日曜 … 6 = 土曜（定型文 weekday.0〜weekday.6） */
  weekday: number;
  /** "8:10"（時の先頭の 0 なし）。読めなければ null */
  time: string | null;
}

type RecordedAt = Pick<PatientEntry, "recorded_at" | "record_date">;

/**
 * 記録日（record_date。JST の日付）の月・日・曜日と、記録した時の表記（+09:00）のままの
 * 時:分。曜日は端末の時差によらず記録日から決める。記録日が読めなければ null。
 */
export function recordedAtParts(entry: RecordedAt): RecordedAtParts | null {
  const date = DATE_PATTERN.exec(entry.record_date);
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
  const time = TIME_PATTERN.exec(entry.recorded_at);
  return {
    month,
    day,
    weekday: utc.getUTCDay(),
    time: time ? `${Number(time[1])}:${time[2]}` : null,
  };
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
  const date = fillTemplate(t("history.date"), {
    month: parts.month,
    day: parts.day,
    weekday: t(`weekday.${parts.weekday}`),
  });
  return parts.time === null ? date : `${date}${parts.time}`;
}

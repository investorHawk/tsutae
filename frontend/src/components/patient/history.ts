/** 自分の記録（P2）の並べ方と日時の出し方。文字は数字と記号だけ（定型文は t() で）。 */
import type { PatientEntry } from "../../api/types";

const TIME_PATTERN = /T(\d{2}):(\d{2})/;

function timeOf(entry: PatientEntry): number {
  const ms = Date.parse(entry.recorded_at);
  return Number.isNaN(ms) ? 0 : ms;
}

/** 記録日時の新しい順（同じなら id の大きい順）に並べた新しい配列。 */
export function newestFirst(entries: readonly PatientEntry[]): PatientEntry[] {
  return [...entries].sort((a, b) => timeOf(b) - timeOf(a) || b.id - a.id);
}

/** "2026-10-31 19:30"。時刻は記録した時の表記（+09:00）のまま。読めなければ日付だけ。 */
export function formatRecordedAt(entry: PatientEntry): string {
  const match = TIME_PATTERN.exec(entry.recorded_at);
  return match
    ? `${entry.record_date} ${match[1]}:${match[2]}`
    : entry.record_date;
}

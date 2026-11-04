/** これまでの記録（P2）の行: 記録と、受診日の区切り（受付の時刻の位置）を新しい順に。 */
import type { PatientEntry, PatientVisitDay } from "../../api/types";
import { newestFirst } from "./history";

export type HistoryRow =
  | { kind: "entry"; entry: PatientEntry }
  | { kind: "visit"; visit: PatientVisitDay };

function msOf(value: string): number {
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? 0 : ms;
}

/**
 * 記録（新しい順）の間に、受診日の区切りを受付の時刻の位置で入れた新しい配列。
 * 受付より後の記録は区切りの上、前の記録は下。受付と同じ時刻の記録は受付の前とみなす
 * （下に置く。db.undo_too_sick_entry の「受付の created_at >= recorded_at なら受付が
 * 後」と同じ）。受診は API の順によらず受付の時刻で並べる。
 */
export function historyRows(
  entries: readonly PatientEntry[],
  visits: readonly PatientVisitDay[],
): HistoryRow[] {
  const pending = [...visits].sort(
    (a, b) => msOf(b.received_at) - msOf(a.received_at),
  );
  const rows: HistoryRow[] = [];
  for (const entry of newestFirst(entries)) {
    const recorded = msOf(entry.recorded_at);
    while (pending.length > 0 && msOf(pending[0]!.received_at) >= recorded) {
      rows.push({ kind: "visit", visit: pending.shift()! });
    }
    rows.push({ kind: "entry", entry });
  }
  return [
    ...rows,
    ...pending.map((visit) => ({ kind: "visit" as const, visit })),
  ];
}

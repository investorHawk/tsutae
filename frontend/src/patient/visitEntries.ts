/**
 * 受診で送る記録（docs/plan-device-records.md §5.5）。文面は持たない。
 * 受付の本文は端末の形から pid と質問の文の写しを外したもの（知らない項目はサーバーが 422 にする）。
 */
import { getVisitWindow } from "../api/patientDevice";
import { submitVisit } from "../api/patient";
import type {
  DeviceEntry,
  VisitEntry,
  VisitWindowResponse,
} from "../api/types";
import { listDeviceEntries } from "./deviceStore";

export function toVisitEntry(entry: DeviceEntry): VisitEntry {
  const { pid: _pid, answers, ...rest } = entry;
  return {
    ...rest,
    answers: answers.map(({ question_key, value, temperature }) => ({
      question_key,
      value,
      temperature,
    })),
  };
}

/** 範囲（両端を含む）の記録を受付の形にする。日付は YYYY-MM-DD なので文字列で比べる。 */
export function entriesInWindow(
  entries: readonly DeviceEntry[],
  window: VisitWindowResponse,
): VisitEntry[] {
  return entries
    .filter((e) => window.start <= e.record_date && e.record_date <= window.end)
    .map(toVisitEntry);
}

/**
 * 範囲を聞き、その中の端末の記録を受付番号と一緒に送る。記録を読めなければ例外で返す
 * （空のまま送って、記録が無かったことにしない）。記録は端末に残す（§5.1）。
 */
export async function sendVisit(
  pid: string,
  receptionNo: string,
): Promise<void> {
  const window = await getVisitWindow(pid);
  const entries = await listDeviceEntries(pid);
  await submitVisit(receptionNo, entriesInWindow(entries, window));
}

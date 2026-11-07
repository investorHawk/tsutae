/** 患者画面のテスト用: 端末の記録を読む・入れる（IndexedDB は fake-indexeddb）。 */
import type { DeviceEntry, EntryCreate } from "../../../api/types";
import {
  deleteDeviceEntry,
  listDeviceEntries,
  saveDeviceEntry,
} from "../../../patient/deviceStore";
import { PID } from "./fixtures";

/** 端末の記録を入力の形（too_sick / by_proxy・answers・free_text）に戻す。 */
function asInput(entry: DeviceEntry): EntryCreate {
  if (entry.kind === "too_sick") {
    return { too_sick: true, by_proxy: entry.by_proxy };
  }
  return {
    by_proxy: entry.by_proxy,
    answers: entry.answers.map(({ question_key, value, temperature }) =>
      temperature === null
        ? { question_key, value }
        : { question_key, value, temperature },
    ),
    free_text: entry.free_text,
  };
}

/** 端末に保存された記録（入力の形）。 */
export async function savedInputs(pid: string = PID): Promise<EntryCreate[]> {
  return (await listDeviceEntries(pid)).map(asInput);
}

/** 端末に記録を入れておく。 */
export async function seedDevice(entries: readonly DeviceEntry[]) {
  for (const entry of entries) {
    await saveDeviceEntry(entry);
  }
}

/** その患者の端末の記録を entries だけにする。 */
export async function seedDeviceOnly(
  entries: readonly DeviceEntry[],
  pid: string = PID,
) {
  for (const entry of await listDeviceEntries(pid)) {
    await deleteDeviceEntry(pid, entry.client_entry_id);
  }
  await seedDevice(entries);
}

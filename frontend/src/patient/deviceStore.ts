/**
 * 端末に置く記録（docs/plan-device-records.md §5.1）。IndexedDB の薄い包み。
 * DB tsutae・store entries・キー client_entry_id・索引 [pid, record_date]。
 * 読むときは必ず仮名ID で絞る（別の番号で登録しても、他の患者の記録を見せない）。
 * 失敗は例外で返す（握りつぶさない。画面は入力を残してエラーを出す）。
 * 接続は操作ごとに開いて閉じる。トランザクションが完了してから解決する。
 */
import type { DeviceEntry, IsoDate } from "../api/types";

const DB_NAME = "tsutae";
const DB_VERSION = 1;
const STORE = "entries";
const BY_PID_DATE = "pid_record_date";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore(STORE, {
        keyPath: "client_entry_id",
      });
      store.createIndex(BY_PID_DATE, ["pid", "record_date"]);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/** 1つのトランザクションで work を行い、完了してから結果を返す。 */
async function inStore<T>(
  mode: IDBTransactionMode,
  work: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const request = work(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request.result);
      const fail = () =>
        reject(tx.error ?? new DOMException("aborted", "AbortError"));
      tx.onerror = fail;
      tx.onabort = fail;
    });
  } finally {
    db.close();
  }
}

let persistTried = false;

/** 消されにくくするよう頼む（起動ごとに最初の保存で1回）。結果に頼らない。 */
function tryPersist(): void {
  if (persistTried) {
    return;
  }
  persistTried = true;
  try {
    void navigator.storage?.persist?.().catch(() => undefined);
  } catch {
    // 頼めなくても記録は保存できている
  }
}

/** 保存する。同じ client_entry_id は置き換える（押し直しても増えない）。 */
export async function saveDeviceEntry(entry: DeviceEntry): Promise<void> {
  await inStore("readwrite", (store) => store.put(entry));
  tryPersist();
}

/** 配列のキーは短い方が先、文字列より配列が後なので、[pid] 〜 [pid, []] がその患者の全て。 */
function pidRange(pid: string): IDBKeyRange {
  return IDBKeyRange.bound([pid], [pid, []]);
}

/** その患者の記録（記録日の順）。 */
export function listDeviceEntries(pid: string): Promise<DeviceEntry[]> {
  return inStore("readonly", (store) =>
    store.index(BY_PID_DATE).getAll(pidRange(pid)),
  );
}

/** その患者のその日の記録。 */
export function deviceEntriesOn(
  pid: string,
  recordDate: IsoDate,
): Promise<DeviceEntry[]> {
  const key = IDBKeyRange.only([pid, recordDate]);
  return inStore("readonly", (store) => store.index(BY_PID_DATE).getAll(key));
}

/** その患者の1件を消す。無ければ何もしない。 */
export async function deleteDeviceEntry(
  pid: string,
  clientEntryId: string,
): Promise<void> {
  await inStore("readwrite", (store) => {
    const found = store.get(clientEntryId) as IDBRequest<
      DeviceEntry | undefined
    >;
    found.onsuccess = () => {
      if (found.result?.pid === pid) {
        store.delete(clientEntryId);
      }
    };
    return found;
  });
}

/** その患者の記録を全て消す（設定の「このスマホの登録と記録を消す」）。他の患者の記録は残す。 */
export async function deleteDeviceEntries(pid: string): Promise<void> {
  await inStore("readwrite", (store) => {
    const cursor = store.index(BY_PID_DATE).openCursor(pidRange(pid));
    cursor.onsuccess = () => {
      if (cursor.result) {
        cursor.result.delete();
        cursor.result.continue();
      }
    };
    return cursor;
  });
}

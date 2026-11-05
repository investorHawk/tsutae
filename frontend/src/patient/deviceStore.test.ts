import { afterEach, describe, expect, it, vi } from "vitest";
import type { DeviceEntry } from "../api/types";
import {
  deleteDeviceEntries,
  deleteDeviceEntry,
  deviceEntriesOn,
  listDeviceEntries,
  saveDeviceEntry,
} from "./deviceStore";

const PID = "P-DEMO0001";
const OTHER = "P-EVAL0001";

function entry(id: string, overrides: Partial<DeviceEntry> = {}): DeviceEntry {
  return {
    pid: PID,
    client_entry_id: id,
    recorded_at: "2026-11-09T20:00:00.000000+09:00",
    record_date: "2026-11-09",
    kind: "answers",
    by_proxy: false,
    skill_version: "regimen-folfox@1",
    answers: [
      {
        question_key: "fever",
        value: "measured",
        temperature: 38.2,
        question_text: "熱を測りましたか",
      },
    ],
    free_text: null,
    ...overrides,
  };
}

function ids(entries: readonly DeviceEntry[]): string[] {
  return entries.map((e) => e.client_entry_id);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("deleteDeviceEntries", () => {
  it("その患者の記録を全て消し、他の患者の記録は残す", async () => {
    await saveDeviceEntry(entry("a"));
    await saveDeviceEntry(entry("b", { record_date: "2026-10-31" }));
    await saveDeviceEntry(entry("other", { pid: OTHER }));
    await deleteDeviceEntries(PID);
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    expect(ids(await listDeviceEntries(OTHER))).toEqual(["other"]);
  });

  it("記録が無くても失敗しない", async () => {
    await expect(deleteDeviceEntries(PID)).resolves.toBeUndefined();
  });

  it("開けなければ例外で返す", async () => {
    vi.stubGlobal("indexedDB", undefined);
    await expect(deleteDeviceEntries(PID)).rejects.toBeDefined();
  });
});

describe("saveDeviceEntry と listDeviceEntries", () => {
  it("保存した1件をそのまま読める", async () => {
    const saved = entry("a");
    await saveDeviceEntry(saved);
    await expect(listDeviceEntries(PID)).resolves.toEqual([saved]);
  });

  it("同じ ID を保存し直すと置き換わる（増えない）", async () => {
    await saveDeviceEntry(entry("a"));
    await saveDeviceEntry(
      entry("a", { recorded_at: "2026-11-09T21:00:00+09:00" }),
    );
    const entries = await listDeviceEntries(PID);
    expect(entries).toHaveLength(1);
    expect(entries[0]!.recorded_at).toBe("2026-11-09T21:00:00+09:00");
  });

  it("記録日の順に返す", async () => {
    await saveDeviceEntry(entry("late", { record_date: "2026-11-09" }));
    await saveDeviceEntry(entry("early", { record_date: "2026-10-31" }));
    expect(ids(await listDeviceEntries(PID))).toEqual(["early", "late"]);
  });

  it("引数を書き換えない", async () => {
    const saved = entry("a");
    const before = structuredClone(saved);
    await saveDeviceEntry(saved);
    expect(saved).toEqual(before);
  });

  it("読み直しても（別の接続でも）残っている", async () => {
    await saveDeviceEntry(entry("a"));
    await saveDeviceEntry(entry("b"));
    expect(ids(await listDeviceEntries(PID))).toEqual(["a", "b"]);
    expect(ids(await listDeviceEntries(PID))).toEqual(["a", "b"]);
  });
});

describe("仮名ID ごとに分ける", () => {
  it("他の患者の記録を返さない", async () => {
    await saveDeviceEntry(entry("mine"));
    await saveDeviceEntry(entry("theirs", { pid: OTHER }));
    expect(ids(await listDeviceEntries(PID))).toEqual(["mine"]);
    expect(ids(await listDeviceEntries(OTHER))).toEqual(["theirs"]);
  });

  it("記録が無い患者は空", async () => {
    await saveDeviceEntry(entry("mine"));
    await expect(listDeviceEntries(OTHER)).resolves.toEqual([]);
  });

  it("その日の記録も他の患者のものを返さない", async () => {
    await saveDeviceEntry(entry("mine"));
    await saveDeviceEntry(entry("theirs", { pid: OTHER }));
    expect(ids(await deviceEntriesOn(PID, "2026-11-09"))).toEqual(["mine"]);
  });

  it("他の患者の記録は消さない", async () => {
    await saveDeviceEntry(entry("theirs", { pid: OTHER }));
    await deleteDeviceEntry(PID, "theirs");
    expect(ids(await listDeviceEntries(OTHER))).toEqual(["theirs"]);
  });
});

describe("deviceEntriesOn", () => {
  it("その日の記録だけを返す", async () => {
    await saveDeviceEntry(entry("today1"));
    await saveDeviceEntry(entry("today2"));
    await saveDeviceEntry(entry("before", { record_date: "2026-11-08" }));
    expect(ids(await deviceEntriesOn(PID, "2026-11-09"))).toEqual([
      "today1",
      "today2",
    ]);
  });
});

describe("deleteDeviceEntry", () => {
  it("その1件だけを消す", async () => {
    await saveDeviceEntry(entry("a"));
    await saveDeviceEntry(entry("b"));
    await deleteDeviceEntry(PID, "a");
    expect(ids(await listDeviceEntries(PID))).toEqual(["b"]);
  });

  it("無い ID を消しても失敗しない（何度呼んでもよい）", async () => {
    await expect(deleteDeviceEntry(PID, "none")).resolves.toBeUndefined();
  });
});

describe("失敗は例外で返す", () => {
  const failure = new DOMException("denied", "SecurityError");

  it("IndexedDB が無い端末", async () => {
    vi.stubGlobal("indexedDB", undefined);
    await expect(saveDeviceEntry(entry("a"))).rejects.toBeInstanceOf(Error);
    await expect(listDeviceEntries(PID)).rejects.toBeInstanceOf(Error);
  });

  it("開くときに例外が出る", async () => {
    vi.stubGlobal("indexedDB", {
      open: () => {
        throw failure;
      },
    });
    await expect(saveDeviceEntry(entry("a"))).rejects.toBe(failure);
  });

  it("開く要求が失敗する", async () => {
    const request = { error: failure } as unknown as IDBOpenDBRequest;
    vi.stubGlobal("indexedDB", {
      open: () => {
        queueMicrotask(() => request.onerror?.(new Event("error")));
        return request;
      },
    });
    await expect(listDeviceEntries(PID)).rejects.toBe(failure);
  });

  it("書き込めない（容量の不足など）", async () => {
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    await expect(saveDeviceEntry(entry("a"))).rejects.toMatchObject({
      name: "QuotaExceededError",
    });
  });

  it("トランザクションが中止されたら成功にしない", async () => {
    const real = IDBObjectStore.prototype.put;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (
      this: IDBObjectStore,
      value: unknown,
    ) {
      const request = real.call(this, value);
      this.transaction.abort();
      return request;
    });
    await expect(saveDeviceEntry(entry("a"))).rejects.toMatchObject({
      name: "AbortError",
    });
    vi.restoreAllMocks();
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
  });
});

describe("navigator.storage.persist", () => {
  async function freshStore() {
    vi.resetModules();
    return import("./deviceStore");
  }

  function stubPersist(persist: () => Promise<boolean>) {
    Object.defineProperty(navigator, "storage", {
      configurable: true,
      value: { persist },
    });
  }

  afterEach(() => {
    delete (navigator as unknown as Record<string, unknown>).storage;
  });

  it("最初の保存のときに1回だけ試す", async () => {
    const store = await freshStore();
    const persist = vi.fn(async () => true);
    stubPersist(persist);
    await store.saveDeviceEntry(entry("a"));
    await store.saveDeviceEntry(entry("b"));
    expect(persist).toHaveBeenCalledTimes(1);
  });

  it("断られても・失敗しても保存は成功する", async () => {
    for (const persist of [
      async () => false,
      async () => {
        throw new Error("x");
      },
      () => {
        throw new Error("x");
      },
    ]) {
      const store = await freshStore();
      stubPersist(persist);
      await expect(store.saveDeviceEntry(entry("a"))).resolves.toBeUndefined();
    }
  });

  it("未対応の端末でも保存は成功する", async () => {
    const store = await freshStore();
    await expect(store.saveDeviceEntry(entry("a"))).resolves.toBeUndefined();
  });

  it("保存に失敗したら試さない（次の保存で試す）", async () => {
    const store = await freshStore();
    const persist = vi.fn(async () => true);
    stubPersist(persist);
    vi.stubGlobal("indexedDB", undefined);
    await expect(store.saveDeviceEntry(entry("a"))).rejects.toBeDefined();
    expect(persist).not.toHaveBeenCalled();
  });
});

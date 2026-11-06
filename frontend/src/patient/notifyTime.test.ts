import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadNotifyTime, saveNotifyTime } from "./notifyTime";

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("notifyTime", () => {
  it("保存が無ければ既定の 20:00", () => {
    expect(loadNotifyTime()).toBe("20:00");
  });

  it("保存した時刻を読む", () => {
    saveNotifyTime("08:30");
    expect(loadNotifyTime()).toBe("08:30");
  });

  it("形の違う値は既定に戻す", () => {
    window.localStorage.setItem("tsutae.notify_time", "08:15");
    expect(loadNotifyTime()).toBe("20:00");
  });

  it("保存領域が使えなくても例外にしない", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(loadNotifyTime()).toBe("20:00");
    expect(() => saveNotifyTime("08:30")).not.toThrow();
  });
});

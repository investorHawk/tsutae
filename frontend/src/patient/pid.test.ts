import { afterEach, describe, expect, it, vi } from "vitest";
import { clearPid, isValidPid, loadPid, restorePid, savePid } from "./pid";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("仮名ID の保存", () => {
  it("形式 P- + 英大文字数字8桁だけを有効とする", () => {
    expect(isValidPid("P-DEMO0001")).toBe(true);
    expect(isValidPid("P-AB12CD34")).toBe(true);
    expect(isValidPid("P-demo0001")).toBe(false);
    expect(isValidPid("P-DEMO001")).toBe(false);
    expect(isValidPid("X-DEMO0001")).toBe(false);
    expect(isValidPid("P-DEMO0001/../x")).toBe(false);
    expect(isValidPid("")).toBe(false);
  });

  it("保存・読み出し・削除", () => {
    expect(loadPid()).toBeNull();
    savePid("P-DEMO0001");
    expect(loadPid()).toBe("P-DEMO0001");
    clearPid();
    expect(loadPid()).toBeNull();
  });

  it("不正な ID は保存しない", () => {
    expect(() => savePid("bad")).toThrow();
    expect(loadPid()).toBeNull();
  });

  it("保存領域に不正な値があれば null", () => {
    window.localStorage.setItem("tsutae.pid", "<script>");
    expect(loadPid()).toBeNull();
  });

  it("savePid: 保存領域に書けなければ例外", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "QuotaExceededError");
    });
    expect(() => savePid("P-DEMO0001")).toThrow();
  });

  it("restorePid: 前の値に戻す・null なら消す", () => {
    savePid("P-NEW00001");
    restorePid("P-OLD00001");
    expect(loadPid()).toBe("P-OLD00001");
    restorePid(null);
    expect(loadPid()).toBeNull();
  });

  it("restorePid: 戻せなくても例外にしない", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "QuotaExceededError");
    });
    expect(() => restorePid("P-OLD00001")).not.toThrow();
  });
});

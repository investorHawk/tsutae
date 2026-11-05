import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearPid,
  isValidPid,
  loadPid,
  normalizePidInput,
  restorePid,
  savePid,
} from "./pid";

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

describe("手で入れた番号の正規化（normalizePidInput）", () => {
  it.each([
    ["そのまま", "P-AB12CD34", "P-AB12CD34"],
    ["前後の空白", "  P-AB12CD34\n", "P-AB12CD34"],
    ["前後の全角の空白", "\u3000P-AB12CD34\u3000", "P-AB12CD34"],
    ["全角の英数", "Ｐ－ＡＢ１２ＣＤ３４", "P-AB12CD34"],
    ["小文字", "p-ab12cd34", "P-AB12CD34"],
    ["全角の小文字", "ｐ－ａｂ１２ｃｄ３４", "P-AB12CD34"],
    ["P- が無い8文字", "AB12CD34", "P-AB12CD34"],
    ["P- が無い小文字の8文字", "ab12cd34", "P-AB12CD34"],
    ["P- が無い全角の8文字", "ＡＢ１２ＣＤ３４", "P-AB12CD34"],
    ["P で始まる8文字にも補う", "PB12CD34", "P-PB12CD34"],
  ])("%s", (_label, input, expected) => {
    expect(normalizePidInput(input)).toBe(expected);
    expect(isValidPid(normalizePidInput(input))).toBe(true);
  });

  it.each([
    ["長音（カタカナ）", "\u30FC"],
    ["長音（半角カタカナ）", "\uFF70"],
    ["全角のハイフンマイナス", "\uFF0D"],
    ["ハイフン", "\u2010"],
    ["ノンブレークハイフン", "\u2011"],
    ["フィギュアダッシュ", "\u2012"],
    ["エヌダッシュ", "\u2013"],
    ["エムダッシュ", "\u2014"],
    ["水平線", "\u2015"],
    ["マイナス", "\u2212"],
    ["罫線", "\u2500"],
    ["小さいハイフンマイナス", "\uFE63"],
  ])("%s はハイフンにする", (_label, dash) => {
    expect(normalizePidInput(`P${dash}AB12CD34`)).toBe("P-AB12CD34");
  });

  it.each([
    ["空", ""],
    ["空白だけ", "   "],
    ["短い", "AB12CD3"],
    ["長い", "AB12CD345"],
    ["P- の後が短い", "P-AB12CD3"],
    ["記号", "AB12CD3!"],
    ["途中の空白", "P-AB12 CD34"],
    ["経路の文字", "P-DEMO0001/../x"],
    ["日本語", "とうろくばんごう"],
    ["別の接頭辞", "X-AB12CD34"],
  ])("%s は形式に通らない", (_label, input) => {
    expect(isValidPid(normalizePidInput(input))).toBe(false);
  });
});

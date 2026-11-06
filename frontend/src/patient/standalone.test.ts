import { afterEach, describe, expect, it, vi } from "vitest";
import {
  needsHomeScreenGuide,
  readDisplayEnv,
  suggestsHomeScreen,
  type DisplayEnv,
} from "./standalone";

const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const IPAD =
  "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const MAC =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const ANDROID =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";
const WINDOWS =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

function env(overrides: Partial<DisplayEnv>): DisplayEnv {
  return {
    userAgent: IPHONE,
    maxTouchPoints: 5,
    navigatorStandalone: false,
    displayModeStandalone: false,
    ...overrides,
  };
}

describe("needsHomeScreenGuide", () => {
  it.each<[string, Partial<DisplayEnv>, boolean]>([
    ["iPhone Safari", {}, true],
    ["iPad Safari", { userAgent: IPAD }, true],
    ["iPad that reports a Mac UA", { userAgent: MAC, maxTouchPoints: 5 }, true],
    [
      "navigator.standalone undefined",
      { navigatorStandalone: undefined },
      true,
    ],
    ["iPhone home screen app", { navigatorStandalone: true }, false],
    ["iPhone display-mode", { displayModeStandalone: true }, false],
    [
      "iPad home screen app with a Mac UA",
      { userAgent: MAC, navigatorStandalone: true },
      false,
    ],
    ["Mac (no touch)", { userAgent: MAC, maxTouchPoints: 0 }, false],
    ["Mac with one touch point", { userAgent: MAC, maxTouchPoints: 1 }, false],
    ["Android browser", { userAgent: ANDROID }, false],
    ["Windows", { userAgent: WINDOWS, maxTouchPoints: 10 }, false],
  ])("%s", (_label, overrides, expected) => {
    expect(needsHomeScreenGuide(env(overrides))).toBe(expected);
  });
});

describe("suggestsHomeScreen", () => {
  it.each<[string, Partial<DisplayEnv>, boolean]>([
    ["Android browser", { userAgent: ANDROID }, true],
    [
      "Android home screen app",
      { userAgent: ANDROID, displayModeStandalone: true },
      false,
    ],
    ["iPhone Safari (the guide instead)", {}, false],
    ["Mac", { userAgent: MAC, maxTouchPoints: 0 }, false],
    ["Windows", { userAgent: WINDOWS }, false],
  ])("%s", (_label, overrides, expected) => {
    expect(suggestsHomeScreen(env(overrides))).toBe(expected);
  });
});

describe("readDisplayEnv", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete (navigator as unknown as Record<string, unknown>).standalone;
  });

  it("reads navigator and works without matchMedia (jsdom has none)", () => {
    const read = readDisplayEnv();
    expect(read.userAgent).toBe(navigator.userAgent);
    expect(read.displayModeStandalone).toBe(false);
    expect(read.navigatorStandalone).toBeUndefined();
  });

  it("reads display-mode and navigator.standalone", () => {
    const matchMedia = vi.fn((query: string) => ({
      matches: query === "(display-mode: standalone)",
    }));
    vi.stubGlobal("matchMedia", matchMedia);
    Object.defineProperty(navigator, "standalone", {
      configurable: true,
      value: true,
    });
    const read = readDisplayEnv();
    expect(read.displayModeStandalone).toBe(true);
    expect(read.navigatorStandalone).toBe(true);
  });
});

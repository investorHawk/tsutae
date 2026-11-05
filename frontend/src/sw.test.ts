// @vitest-environment node
/**
 * public/sw.js の動き。実物のファイルを偽の self の上で実行して確かめる
 * （docs/plan-device-records.md §4.2）。
 */
import { beforeAll, describe, expect, it, vi } from "vitest";

interface Fs {
  readFileSync(path: URL, encoding: "utf8"): string;
}

type Listener = (event: FakeEvent) => void;

interface FakeEvent {
  waitUntil: (work: Promise<unknown>) => void;
  data?: { json: () => unknown } | null;
  notification?: { close: () => void };
}

interface FakeWindow {
  url: string;
  navigate: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
}

let source = "";

beforeAll(async () => {
  // tsconfig の types に node が無いため、型は必要な分だけ書く（homeScreen.test.ts と同じ）
  const fs = (await import(/* @vite-ignore */ `node:${"fs"}`)) as Fs;
  source = fs.readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
});

function fakeWindow(path: string): FakeWindow {
  const win: FakeWindow = {
    url: `https://tsutae.test${path}`,
    navigate: vi.fn(async () => win),
    focus: vi.fn(async () => win),
  };
  return win;
}

/** sw.js を偽の self の上で実行し、登録されたハンドラを返す。 */
function loadWorker({
  windows = [] as FakeWindow[],
  badge = true,
  badgeFails = false,
} = {}) {
  const listeners = new Map<string, Listener>();
  const showNotification = vi.fn(async () => undefined);
  const setAppBadge = vi.fn(async () => {
    if (badgeFails) {
      throw new Error("badge is not available");
    }
  });
  const openWindow = vi.fn(async () => null);
  const matchAll = vi.fn(async () => windows);
  const self = {
    addEventListener: (type: string, listener: Listener) => {
      listeners.set(type, listener);
    },
    registration: { showNotification },
    clients: { matchAll, openWindow, claim: vi.fn(async () => undefined) },
    navigator: badge ? { setAppBadge } : {},
    skipWaiting: vi.fn(async () => undefined),
  };
  new Function("self", source)(self);
  return { listeners, showNotification, setAppBadge, openWindow, matchAll };
}

/** ハンドラを呼び、waitUntil に渡された仕事が全て終わるまで待つ。 */
async function dispatch(
  listeners: Map<string, Listener>,
  type: string,
  fields: Partial<FakeEvent> = {},
) {
  const work: Promise<unknown>[] = [];
  const listener = listeners.get(type);
  if (!listener) {
    throw new Error(`${type} のハンドラが無い`);
  }
  listener({ waitUntil: (p) => work.push(p), ...fields });
  expect(work.length, `${type} は waitUntil を呼ぶ`).toBeGreaterThan(0);
  await Promise.all(work);
}

const PAYLOAD = { title: "Title", body: "Body", url: "/today", badge: 1 };

describe("sw.js: push", () => {
  it("本文の title と body で通知を出し、バッジを付ける", async () => {
    const w = loadWorker();
    await dispatch(w.listeners, "push", { data: { json: () => PAYLOAD } });
    expect(w.showNotification).toHaveBeenCalledTimes(1);
    const [title, options] = w.showNotification.mock.calls[0] as unknown as [
      string,
      { body?: string; icon?: string },
    ];
    expect(title).toBe("Title");
    expect(options.body).toBe("Body");
    expect(options.icon).toBe("/icon-192.png");
    expect(w.setAppBadge).toHaveBeenCalledWith(1);
  });

  it.each([
    [
      "JSON が読めない",
      {
        json: () => {
          throw new SyntaxError("bad json");
        },
      },
    ],
    ["本文が無い", null],
    ["title が文字列でない", { json: () => ({ title: 1, body: "Body" }) }],
    ["null が返る", { json: () => null }],
  ])("%s ときもタイトルだけで通知を出す", async (_label, data) => {
    const w = loadWorker();
    await dispatch(w.listeners, "push", { data });
    expect(w.showNotification).toHaveBeenCalledTimes(1);
    const [title, options] = w.showNotification.mock.calls[0] as unknown as [
      string,
      { body?: string },
    ];
    expect(title).toBe("つたえ");
    expect(options.body).toBeUndefined();
  });

  it("setAppBadge が無い端末でも通知を出す", async () => {
    const w = loadWorker({ badge: false });
    await dispatch(w.listeners, "push", { data: { json: () => PAYLOAD } });
    expect(w.showNotification).toHaveBeenCalledTimes(1);
  });

  it("バッジが失敗しても通知を出し、失敗を外へ出さない", async () => {
    const w = loadWorker({ badgeFails: true });
    await dispatch(w.listeners, "push", { data: { json: () => PAYLOAD } });
    expect(w.showNotification).toHaveBeenCalledTimes(1);
  });
});

describe("sw.js: notificationclick", () => {
  const click = async (w: ReturnType<typeof loadWorker>) => {
    const close = vi.fn();
    await dispatch(w.listeners, "notificationclick", {
      notification: { close },
    });
    expect(close).toHaveBeenCalledTimes(1);
  };

  it("開いている画面があれば /today にして手前に出す", async () => {
    const win = fakeWindow("/history");
    const w = loadWorker({ windows: [win] });
    await click(w);
    expect(win.navigate).toHaveBeenCalledWith("/today");
    expect(win.focus).toHaveBeenCalledTimes(1);
    expect(w.openWindow).not.toHaveBeenCalled();
    expect(w.matchAll).toHaveBeenCalledWith({
      type: "window",
      includeUncontrolled: true,
    });
  });

  it("すでに /today なら読み直さず（書きかけを消さず）手前に出すだけ", async () => {
    const win = fakeWindow("/today");
    const w = loadWorker({ windows: [win] });
    await click(w);
    expect(win.navigate).not.toHaveBeenCalled();
    expect(win.focus).toHaveBeenCalledTimes(1);
  });

  it("開いている画面が無ければ /today を開く", async () => {
    const w = loadWorker();
    await click(w);
    expect(w.openWindow).toHaveBeenCalledWith("/today");
  });

  it("医師の画面は動かさず /today を別に開く", async () => {
    const win = fakeWindow("/doctor/patients");
    const w = loadWorker({ windows: [win] });
    await click(w);
    expect(win.navigate).not.toHaveBeenCalled();
    expect(w.openWindow).toHaveBeenCalledWith("/today");
  });

  it("画面を動かせなければ /today を開く", async () => {
    const win = fakeWindow("/history");
    win.navigate.mockRejectedValue(new TypeError("not controlled"));
    const w = loadWorker({ windows: [win] });
    await click(w);
    expect(w.openWindow).toHaveBeenCalledWith("/today");
  });
});

describe("sw.js: 登録の直後", () => {
  it("待たずに有効になり、開いている画面を受け持つ（navigate に要る）", async () => {
    const w = loadWorker();
    expect(w.listeners.has("install")).toBe(true);
    await dispatch(w.listeners, "activate");
  });

  it("通信のハンドラを登録しない", () => {
    const w = loadWorker();
    expect([...w.listeners.keys()].sort()).toEqual([
      "activate",
      "install",
      "notificationclick",
      "push",
    ]);
  });
});

// @vitest-environment node
/**
 * public/sw.js の動き。実物のファイルを偽の self の上で実行して確かめる
 * （docs/plan-device-records.md §4.2）。
 */
import { beforeAll, describe, expect, it, vi } from "vitest";
import { OPEN_TODAY_MESSAGE } from "./patient/pushDevice";

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
  postMessage: ReturnType<typeof vi.fn>;
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
    postMessage: vi.fn(),
  };
  return win;
}

/** sw.js を偽の self の上で実行し、登録されたハンドラを返す。 */
function loadWorker({
  windows = [] as FakeWindow[],
  badge = true,
  badgeFails = false,
  showResult = Promise.resolve() as Promise<unknown>,
  claimResult = Promise.resolve() as Promise<unknown>,
} = {}) {
  const listeners = new Map<string, Listener>();
  const showNotification = vi.fn(() => showResult);
  const setAppBadge = vi.fn(async () => {
    if (badgeFails) {
      throw new Error("badge is not available");
    }
  });
  const openWindow = vi.fn(async () => null);
  const matchAll = vi.fn(async () => windows);
  const claim = vi.fn(() => claimResult);
  const skipWaiting = vi.fn(async () => undefined);
  const self = {
    addEventListener: (type: string, listener: Listener) => {
      listeners.set(type, listener);
    },
    registration: { showNotification },
    clients: { matchAll, openWindow, claim },
    navigator: badge ? { setAppBadge } : {},
    skipWaiting,
  };
  new Function("self", source)(self);
  return {
    listeners,
    showNotification,
    setAppBadge,
    openWindow,
    matchAll,
    claim,
    skipWaiting,
  };
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

/** あとで終わらせられる Promise。 */
function deferred() {
  let finish: () => void = () => undefined;
  const promise = new Promise<void>((resolve) => {
    finish = resolve;
  });
  return { promise, finish };
}

/**
 * ハンドラを呼び、waitUntil の仕事の完了を見張る（dispatch と違って待たない）。
 * 仕事が残っているあいだ isSettled は false。
 */
function dispatchWatching(
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
  let settled = false;
  const all = Promise.all(work).then(() => {
    settled = true;
  });
  return { all, isSettled: () => settled };
}

/** 待ち中の Promise を一通り進める（タイマーを使わない仕事はこれで終わる）。 */
async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

const PAYLOAD = { title: "Title", body: "Body", url: "/today", badge: 1 };

describe("sw.js: push", () => {
  it("通知を出し終えるまで waitUntil の仕事が終わらない（先に止められない）", async () => {
    const shown = deferred();
    const w = loadWorker({ showResult: shown.promise });
    const watch = dispatchWatching(w.listeners, "push", {
      data: { json: () => PAYLOAD },
    });
    await flush();
    expect(w.showNotification).toHaveBeenCalledTimes(1);
    expect(watch.isSettled()).toBe(false);
    shown.finish();
    await watch.all;
    expect(watch.isSettled()).toBe(true);
  });

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

  it("すでに /today なら、日付が変わっていないかを画面に確かめさせる", async () => {
    const win = fakeWindow("/today");
    const w = loadWorker({ windows: [win] });
    await click(w);
    expect(win.postMessage).toHaveBeenCalledWith({ type: OPEN_TODAY_MESSAGE });
    expect(win.focus).toHaveBeenCalledTimes(1);
  });

  it("別の画面から移すときは知らせない（読み込み直されるので要らない）", async () => {
    const win = fakeWindow("/history");
    const w = loadWorker({ windows: [win] });
    await click(w);
    expect(win.postMessage).not.toHaveBeenCalled();
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

  it("別のタブで開いた医師のレポートも動かさず /today を別に開く", async () => {
    const win = fakeWindow("/api/doctor/visits/3/report");
    const w = loadWorker({ windows: [win] });
    await click(w);
    expect(win.navigate).not.toHaveBeenCalled();
    expect(win.focus).not.toHaveBeenCalled();
    expect(w.openWindow).toHaveBeenCalledWith("/today");
  });

  it("レポートのタブが先に見つかっても、患者の画面を使う", async () => {
    const report = fakeWindow("/api/doctor/visits/3/report");
    const patient = fakeWindow("/history");
    const w = loadWorker({ windows: [report, patient] });
    await click(w);
    expect(report.navigate).not.toHaveBeenCalled();
    expect(patient.navigate).toHaveBeenCalledWith("/today");
    expect(w.openWindow).not.toHaveBeenCalled();
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
  it("install で待たずに有効になる（直した sw.js に古い版が残らない）", () => {
    const w = loadWorker();
    const install = w.listeners.get("install");
    if (!install) {
      throw new Error("install のハンドラが無い");
    }
    expect(w.skipWaiting).not.toHaveBeenCalled();
    install({ waitUntil: () => undefined });
    expect(w.skipWaiting).toHaveBeenCalledTimes(1);
  });

  it("activate で開いている画面を受け持ち、終わるまで待つ（navigate に要る）", async () => {
    const claimed = deferred();
    const w = loadWorker({ claimResult: claimed.promise });
    const watch = dispatchWatching(w.listeners, "activate");
    await flush();
    expect(w.claim).toHaveBeenCalledTimes(1);
    expect(watch.isSettled()).toBe(false);
    claimed.finish();
    await watch.all;
    expect(watch.isSettled()).toBe(true);
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

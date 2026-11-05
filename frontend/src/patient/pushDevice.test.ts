import { afterEach, describe, expect, it, vi } from "vitest";
import {
  base64UrlToBytes,
  clearDeliveredNotifications,
  findSubscription,
  isPushSupported,
  subscribeDevice,
  toSubscriptionRequest,
} from "./pushDevice";

const KEY = "AQID"; // base64url で 01 02 03
const OTHER_KEY = "BAUG"; // 04 05 06

function bytes(...values: number[]): ArrayBuffer {
  return new Uint8Array(values).buffer;
}

function fakeSubscription(key: ArrayBuffer | null = bytes(1, 2, 3)) {
  return {
    endpoint: "https://web.push.apple.com/Q",
    options: { applicationServerKey: key },
    toJSON: () => ({
      endpoint: "https://web.push.apple.com/Q",
      keys: { p256dh: "p", auth: "a" },
    }),
    unsubscribe: vi.fn(async () => true),
  };
}

function setNavigator(name: string, value: unknown) {
  Object.defineProperty(navigator, name, { configurable: true, value });
  installed.push(name);
}

const installed: string[] = [];

function fakeRegistration(existing: unknown = null) {
  return {
    pushManager: {
      getSubscription: vi.fn(async () => existing),
      subscribe: vi.fn(async () => fakeSubscription()),
    },
    getNotifications: vi.fn(async () => [] as { close: () => void }[]),
  };
}

function installWorker(registration: unknown) {
  const worker = {
    register: vi.fn(async () => registration),
    getRegistration: vi.fn(async () => registration),
    ready: Promise.resolve(registration),
  };
  setNavigator("serviceWorker", worker);
  return worker;
}

afterEach(() => {
  for (const name of installed.splice(0)) {
    delete (navigator as unknown as Record<string, unknown>)[name];
  }
  vi.unstubAllGlobals();
});

describe("base64UrlToBytes", () => {
  it.each([
    ["AQID", [1, 2, 3]],
    ["AQI", [1, 2]],
    ["AQ", [1]],
    ["-_-_", [251, 255, 191]],
    ["AQI=", [1, 2]],
  ])("%s", (text, expected) => {
    expect([...base64UrlToBytes(text)]).toEqual(expected);
  });
});

describe("isPushSupported", () => {
  it("PushManager が無ければ未対応（iPhone のホーム画面の外）", () => {
    installWorker(null);
    vi.stubGlobal("Notification", {});
    expect(isPushSupported()).toBe(false);
  });

  it("Service Worker が無ければ未対応（https でない）", () => {
    vi.stubGlobal("PushManager", class {});
    vi.stubGlobal("Notification", {});
    expect(isPushSupported()).toBe(false);
  });

  it("Notification が無ければ未対応", () => {
    installWorker(null);
    vi.stubGlobal("PushManager", class {});
    expect(isPushSupported()).toBe(false);
  });

  it("3つとも揃えば対応", () => {
    installWorker(null);
    vi.stubGlobal("PushManager", class {});
    vi.stubGlobal("Notification", {});
    expect(isPushSupported()).toBe(true);
  });
});

describe("findSubscription", () => {
  it("Service Worker を登録せず、登録が無ければ null", async () => {
    const worker = {
      register: vi.fn(),
      getRegistration: vi.fn(async () => undefined),
    };
    setNavigator("serviceWorker", worker);
    await expect(findSubscription(KEY)).resolves.toBeNull();
    expect(worker.register).not.toHaveBeenCalled();
  });

  it("今の公開鍵の登録を返す", async () => {
    const sub = fakeSubscription();
    installWorker(fakeRegistration(sub));
    await expect(findSubscription(KEY)).resolves.toBe(sub);
  });

  it("違う公開鍵の登録は無いものとして扱う（鍵を作り直した後）", async () => {
    installWorker(fakeRegistration(fakeSubscription()));
    await expect(findSubscription(OTHER_KEY)).resolves.toBeNull();
  });

  it("公開鍵が読めない端末は、登録をそのまま使う", async () => {
    const sub = fakeSubscription(null);
    installWorker(fakeRegistration(sub));
    await expect(findSubscription(KEY)).resolves.toBe(sub);
  });
});

describe("subscribeDevice", () => {
  it("有効になる前は subscribe しない（例外になる端末がある）", async () => {
    const registration = fakeRegistration();
    let active = false;
    registration.pushManager.subscribe.mockImplementation(async () => {
      if (!active) {
        throw new Error("no active service worker");
      }
      return fakeSubscription();
    });
    let activate: () => void = () => undefined;
    const ready = new Promise((resolve) => {
      activate = () => {
        active = true;
        resolve(registration);
      };
    });
    const worker = {
      register: vi.fn(async () => registration),
      getRegistration: vi.fn(async () => registration),
      ready,
    };
    setNavigator("serviceWorker", worker);
    const subscribing = subscribeDevice(KEY);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(worker.register).toHaveBeenCalledWith("/sw.js");
    expect(registration.pushManager.subscribe).not.toHaveBeenCalled();
    activate();
    await expect(subscribing).resolves.toBeDefined();
    expect(registration.pushManager.subscribe).toHaveBeenCalledTimes(1);
  });

  it("/sw.js を登録し、userVisibleOnly で登録する", async () => {
    const registration = fakeRegistration();
    const worker = installWorker(registration);
    await subscribeDevice(KEY);
    expect(worker.register).toHaveBeenCalledWith("/sw.js");
    const [options] = registration.pushManager.subscribe.mock
      .calls[0] as unknown as [
      { userVisibleOnly: boolean; applicationServerKey: Uint8Array },
    ];
    expect(options.userVisibleOnly).toBe(true);
    expect([...options.applicationServerKey]).toEqual([1, 2, 3]);
  });

  it("同じ公開鍵の登録が残っていれば、それを使う", async () => {
    const sub = fakeSubscription();
    const registration = fakeRegistration(sub);
    installWorker(registration);
    await expect(subscribeDevice(KEY)).resolves.toBe(sub);
    expect(registration.pushManager.subscribe).not.toHaveBeenCalled();
  });

  it("違う公開鍵の登録は解除してから登録し直す", async () => {
    const old = fakeSubscription();
    const registration = fakeRegistration(old);
    installWorker(registration);
    await subscribeDevice(OTHER_KEY);
    expect(old.unsubscribe).toHaveBeenCalledTimes(1);
    expect(registration.pushManager.subscribe).toHaveBeenCalledTimes(1);
  });
});

describe("toSubscriptionRequest", () => {
  it("endpoint・鍵・時刻を API の形にする", () => {
    const sub = fakeSubscription() as unknown as PushSubscription;
    expect(toSubscriptionRequest(sub, "08:30")).toEqual({
      endpoint: "https://web.push.apple.com/Q",
      keys: { p256dh: "p", auth: "a" },
      notify_time: "08:30",
    });
  });

  it("鍵が無ければ例外（送っても 422 になるだけ）", () => {
    const sub = {
      toJSON: () => ({ endpoint: "https://web.push.apple.com/Q" }),
    } as unknown as PushSubscription;
    expect(() => toSubscriptionRequest(sub, "08:30")).toThrow();
  });
});

describe("clearDeliveredNotifications", () => {
  it("バッジを消し、表示中の通知を全て閉じる", async () => {
    const shown = [{ close: vi.fn() }, { close: vi.fn() }];
    const registration = fakeRegistration();
    registration.getNotifications.mockResolvedValue(shown);
    installWorker(registration);
    const clearAppBadge = vi.fn(async () => undefined);
    setNavigator("clearAppBadge", clearAppBadge);
    await clearDeliveredNotifications();
    expect(clearAppBadge).toHaveBeenCalledTimes(1);
    expect(shown[0]?.close).toHaveBeenCalledTimes(1);
    expect(shown[1]?.close).toHaveBeenCalledTimes(1);
  });

  it("どれも無い端末では何もしない", async () => {
    await expect(clearDeliveredNotifications()).resolves.toBeUndefined();
  });

  it("Service Worker を新しく登録しない", async () => {
    const worker = installWorker(undefined);
    await clearDeliveredNotifications();
    expect(worker.register).not.toHaveBeenCalled();
  });

  it("どちらかが失敗しても外へ出さず、もう片方は行う", async () => {
    const shown = [{ close: vi.fn() }];
    const registration = fakeRegistration();
    registration.getNotifications.mockResolvedValue(shown);
    installWorker(registration);
    setNavigator(
      "clearAppBadge",
      vi.fn(async () => {
        throw new Error("not allowed");
      }),
    );
    await expect(clearDeliveredNotifications()).resolves.toBeUndefined();
    expect(shown[0]?.close).toHaveBeenCalledTimes(1);
  });
});

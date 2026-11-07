/**
 * 端末の通知の API の偽物（jsdom には Notification・PushManager・serviceWorker が無い）。
 * calls に呼ばれた順を残す。endpoint・鍵は API の fixture と同じ値。
 */
import { vi } from "vitest";
import { base64UrlToBytes } from "../../../patient/pushDevice";
import { apiFixture } from "../../../test/apiFixtures";

interface SubscribeRequestFixture {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

const REQUEST = apiFixture("patient_push_subscribe")
  .request as SubscribeRequestFixture;

export const ENDPOINT = REQUEST.endpoint;
export const KEYS = REQUEST.keys;
export const PUBLIC_KEY = (
  apiFixture("patient_push_config").body as { public_key: string }
).public_key;

export interface FakePushOptions {
  /** 開いたときの許可の状態 */
  permission?: NotificationPermission;
  /** 許可を求めたときの答え */
  answer?: NotificationPermission;
  /** 最初から登録がある */
  subscribed?: boolean;
  /** subscribe が失敗する */
  subscribeError?: Error;
  /** unsubscribe が失敗する */
  unsubscribeError?: Error;
  /** unsubscribe が例外を出さずに false を返す（解除できなかった） */
  unsubscribeReturnsFalse?: boolean;
}

export interface FakePush {
  calls: string[];
  requestPermission: ReturnType<typeof vi.fn>;
  register: ReturnType<typeof vi.fn>;
  subscribe: ReturnType<typeof vi.fn>;
  clearAppBadge: ReturnType<typeof vi.fn>;
  shown: { close: ReturnType<typeof vi.fn> }[];
  /** 知らせの受け取りを始めた（navigator.serviceWorker.startMessages） */
  startMessages: ReturnType<typeof vi.fn>;
  /** Service Worker から画面へ知らせを送る（通知を押した、など） */
  postFromWorker: (data: unknown) => void;
  /** 今の許可の状態を変える（端末の設定で直した、など） */
  setPermission: (permission: NotificationPermission) => void;
  isSubscribed: () => boolean;
  uninstall: () => void;
}

function defineOnNavigator(name: string, value: unknown) {
  Object.defineProperty(navigator, name, { configurable: true, value });
}

function removeFromNavigator(name: string) {
  delete (navigator as unknown as Record<string, unknown>)[name];
}

/** 通知を使える端末にする。テストの後で uninstall を呼ぶ。 */
export function installFakePush(options: FakePushOptions = {}): FakePush {
  const calls: string[] = [];
  const notification = {
    permission: options.permission ?? "default",
    requestPermission: vi.fn(async () => {
      calls.push("requestPermission");
      notification.permission = options.answer ?? "granted";
      return notification.permission;
    }),
  };
  let current: unknown = null;
  const makeSubscription = () => {
    const subscription = {
      endpoint: ENDPOINT,
      options: { applicationServerKey: base64UrlToBytes(PUBLIC_KEY).buffer },
      toJSON: () => ({ endpoint: ENDPOINT, keys: KEYS }),
      unsubscribe: vi.fn(async () => {
        calls.push("unsubscribe");
        if (options.unsubscribeError) {
          throw options.unsubscribeError;
        }
        // 本物と同じく、すでに解除された登録の解除は false（例外にならない）
        if (options.unsubscribeReturnsFalse || current !== subscription) {
          return false;
        }
        current = null;
        return true;
      }),
    };
    return subscription;
  };
  // 本物と同じく、register の直後は有効でなく、ready が解決してから subscribe できる
  let active = options.subscribed === true;
  const subscribe = vi.fn(async () => {
    calls.push("subscribe");
    if (!active) {
      throw new Error("no active service worker");
    }
    if (options.subscribeError) {
      throw options.subscribeError;
    }
    current = makeSubscription();
    return current;
  });
  const shown = [{ close: vi.fn() }];
  const registration = {
    pushManager: { getSubscription: async () => current, subscribe },
    getNotifications: async () => shown,
  };
  let registered = false;
  const register = vi.fn(async () => {
    calls.push("register");
    registered = true;
    return registration;
  });
  if (options.subscribed) {
    current = makeSubscription();
    registered = true;
  }
  const messageListeners = new Set<(event: { data: unknown }) => void>();
  const startMessages = vi.fn();
  defineOnNavigator("serviceWorker", {
    register,
    startMessages,
    addEventListener: (
      _type: string,
      listener: (event: { data: unknown }) => void,
    ) => messageListeners.add(listener),
    removeEventListener: (
      _type: string,
      listener: (event: { data: unknown }) => void,
    ) => messageListeners.delete(listener),
    getRegistration: async () => (registered ? registration : undefined),
    get ready() {
      // 読むと、一度タスクを挟んでから有効になる（読まずに subscribe すると例外）
      return new Promise((resolve) => {
        setTimeout(() => {
          active = true;
          resolve(registration);
        }, 0);
      });
    },
  });
  const clearAppBadge = vi.fn(async () => undefined);
  defineOnNavigator("clearAppBadge", clearAppBadge);
  vi.stubGlobal("Notification", notification);
  vi.stubGlobal("PushManager", class {});
  return {
    calls,
    requestPermission: notification.requestPermission,
    register,
    subscribe,
    clearAppBadge,
    shown,
    startMessages,
    postFromWorker: (data) => {
      messageListeners.forEach((listener) => listener({ data }));
    },
    setPermission: (permission) => {
      notification.permission = permission;
    },
    isSubscribed: () => current !== null,
    uninstall: () => {
      removeFromNavigator("serviceWorker");
      removeFromNavigator("clearAppBadge");
      vi.unstubAllGlobals();
    },
  };
}

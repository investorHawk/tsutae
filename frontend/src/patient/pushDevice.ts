/**
 * 端末の通知の API の薄い包み（docs/plan-device-records.md §4.2・§4.5）。
 * Service Worker の登録は subscribeDevice（設定でオンにしたとき）だけが行う。
 */
import type { PushSubscriptionRequest } from "../api/patientPush";

const SERVICE_WORKER_URL = "/sw.js";

/** 通知を押したときに sw.js が /today の画面へ送る知らせの type（sw.js と同じ値）。 */
export const OPEN_TODAY_MESSAGE = "tsutae.open-today";

export function isPushSupported(): boolean {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** 対応していない端末は "default"（呼ぶ側は pushStatusOf で未対応を先に見る）。 */
export function currentPermission(): NotificationPermission {
  return "Notification" in window ? Notification.permission : "default";
}

/** 許可を求める。iPhone は押した直後でないと出せないので、await より前に呼ぶこと。 */
export function askPermission(): Promise<NotificationPermission> {
  return Notification.requestPermission();
}

/** 公開鍵（base64url。パディングなしでもよい）をバイト列にする。 */
export function base64UrlToBytes(text: string): Uint8Array {
  const base64 = text.replace(/=+$/, "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

/** 登録が今の公開鍵のものか。鍵を読めない端末は同じと見なす。 */
function usesKey(subscription: PushSubscription, publicKey: string): boolean {
  const current = subscription.options?.applicationServerKey;
  if (!current) {
    return true;
  }
  const actual = new Uint8Array(current);
  const expected = base64UrlToBytes(publicKey);
  return (
    actual.length === expected.length &&
    actual.every((value, i) => value === expected[i])
  );
}

/**
 * この端末にある今の公開鍵の登録。無ければ null。Service Worker は登録しない。
 * 鍵を作り直す前の登録はサーバーから送れないので、無いものとして扱う（オンに見せない）。
 */
export async function findSubscription(
  publicKey: string,
): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  return subscription && usesKey(subscription, publicKey) ? subscription : null;
}

/** この端末にまだこの endpoint の登録があるか（鍵は見ない）。 */
export async function isStillSubscribed(endpoint: string): Promise<boolean> {
  const registration = await navigator.serviceWorker.getRegistration();
  const current = await registration?.pushManager.getSubscription();
  return current?.endpoint === endpoint;
}

/**
 * Service Worker を登録し、通知の登録を返す。許可は呼ぶ前に取っておく。
 * 別の鍵の登録が残っていると subscribe が例外になるので、先に解除する。
 */
export async function subscribeDevice(
  publicKey: string,
): Promise<PushSubscription> {
  await navigator.serviceWorker.register(SERVICE_WORKER_URL);
  // 有効になる前に subscribe すると例外になる端末がある
  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  if (existing && usesKey(existing, publicKey)) {
    return existing;
  }
  await existing?.unsubscribe();
  return registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: base64UrlToBytes(publicKey),
  });
}

/** PUT push-subscription の本文。鍵が欠けた登録は例外。 */
export function toSubscriptionRequest(
  subscription: PushSubscription,
  notifyTime: string,
): PushSubscriptionRequest {
  const { endpoint, keys } = subscription.toJSON();
  const p256dh = keys?.p256dh;
  const auth = keys?.auth;
  if (!endpoint || !p256dh || !auth) {
    throw new Error("push subscription has no keys");
  }
  return { endpoint, keys: { p256dh, auth }, notify_time: notifyTime };
}

/** 通知を押した知らせを受ける。解除の関数を返す。未対応の端末では何もしない。 */
export function onOpenTodayMessage(listener: () => void): () => void {
  if (!("serviceWorker" in navigator)) {
    return () => undefined;
  }
  const worker = navigator.serviceWorker;
  const onMessage = (event: MessageEvent) => {
    if (event.data?.type === OPEN_TODAY_MESSAGE) {
      listener();
    }
  };
  worker.addEventListener("message", onMessage);
  // addEventListener だけでは受け取りが始まらないことがある
  worker.startMessages();
  return () => worker.removeEventListener("message", onMessage);
}

async function closeShownNotifications(): Promise<void> {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  const registration = await navigator.serviceWorker.getRegistration();
  const shown = await registration?.getNotifications();
  shown?.forEach((notification) => notification.close());
}

async function clearBadge(): Promise<void> {
  if ("clearAppBadge" in navigator) {
    await navigator.clearAppBadge();
  }
}

/** バッジと表示中の通知を消す。無い端末では何もしない。失敗しても画面を止めない。 */
export async function clearDeliveredNotifications(): Promise<void> {
  await Promise.allSettled([clearBadge(), closeShownNotifications()]);
}

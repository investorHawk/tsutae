/*
 * 毎日のお知らせ専用の Service Worker（docs/plan-device-records.md §4.2）。
 * 通信には手を出さない（オフラインは範囲外）。登録は設定で患者がオンにしたときだけ。
 *
 * 送るかどうかはサーバーが決める。iPhone は通知を出さない push が続くと登録を取り消される
 * おそれがあるので、届いた push は端末で握りつぶさず、本文が読めなくても必ず通知を出す。
 */
const FALLBACK_TITLE = "つたえ";
const TODAY_PATH = "/today";
const OPEN_TODAY_MESSAGE = "tsutae.open-today";

/** 通知の中身。読めないときはタイトルだけ。 */
function contentOf(event) {
  try {
    const data = event.data.json();
    if (typeof data.title === "string" && data.title !== "") {
      return {
        title: data.title,
        options: {
          body: typeof data.body === "string" ? data.body : undefined,
          icon: "/icon-192.png",
        },
      };
    }
  } catch {
    // 下のタイトルだけの通知にする
  }
  return { title: FALLBACK_TITLE, options: { icon: "/icon-192.png" } };
}

/** バッジは付かない端末がある。失敗しても通知は止めない。 */
async function setBadge() {
  try {
    await self.navigator.setAppBadge?.(1);
  } catch {
    // 通知が出ていれば足りる
  }
}

async function showDaily(event) {
  const { title, options } = contentOf(event);
  await Promise.all([
    self.registration.showNotification(title, options),
    setBadge(),
  ]);
}

function pathOf(client) {
  return new URL(client.url).pathname;
}

/** 患者の画面か。医師の画面と、別のタブで開いた医師のレポート（/api/doctor/...）は動かさない。 */
function isPatientScreen(client) {
  const path = pathOf(client);
  return !path.startsWith("/doctor") && !path.startsWith("/api/");
}

/** 開いている患者の画面を /today にして手前に出す。無ければ開く。 */
async function openToday() {
  const windows = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  });
  const target = windows.find(isPatientScreen);
  if (!target) {
    return self.clients.openWindow(TODAY_PATH);
  }
  try {
    if (pathOf(target) === TODAY_PATH) {
      // 動かさない（読み直すと書きかけの入力が消える）。画面を残した iPhone では前の日の画面の
      // ことがあるので、日付が変わっていないかは画面に確かめさせる（useNewDayCheck）
      target.postMessage({ type: OPEN_TODAY_MESSAGE });
      return await target.focus();
    }
    const moved = await target.navigate(TODAY_PATH);
    return await (moved ?? target).focus();
  } catch {
    return self.clients.openWindow(TODAY_PATH);
  }
}

self.addEventListener("install", () => {
  self.skipWaiting();
});

// navigate は受け持っている画面にしか使えないので、開いている画面をすぐ受け持つ
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  event.waitUntil(showDaily(event));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(openToday());
});

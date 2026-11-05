/** 通知の操作（端末の登録とサーバーの登録を揃える）。画面の状態は持たない。 */
import { isApiError } from "../../api/http";
import {
  deletePushSubscription,
  putPushSubscription,
  sendPushTest,
} from "../../api/patientPush";
import { loadNotifyTime, saveNotifyTime } from "../../patient/notifyTime";
import {
  isStillSubscribed,
  subscribeDevice,
  toSubscriptionRequest,
} from "../../patient/pushDevice";
import { GENERIC_ERROR_KEY } from "./patientApi";

const TEST_TOO_SOON_KEY = "notify.test_too_soon";

/** 送信先に消された登録の案内（オンにし直すと新しい登録になる）。 */
export const SUBSCRIPTION_GONE_KEY = "notify.expired";

/** サーバーが「送信先に消された登録」と答えた（PUT の 410）。 */
export function isSubscriptionGone(err: unknown): boolean {
  return isApiError(err) && err.status === 410;
}

/** 消された登録を端末でも解除する。解除できなくても次の送り直しでまた試す。 */
export async function dropGoneSubscription(
  subscription: PushSubscription,
): Promise<void> {
  await subscription.unsubscribe().catch(() => false);
}

let lastSave: Promise<unknown> = Promise.resolve();

/** 登録の PUT が全て終わるのを待つ（端末の時刻を読む前に）。失敗しない。 */
export function savesSettled(): Promise<unknown> {
  return lastSave;
}

/**
 * サーバーに登録・時刻を送り、受け入れられた時刻を端末にも控える。
 * PUT は呼ばれた順に1本ずつ送る（時刻の変更と送り直しが重なっても、古い時刻が後から届いて
 * サーバーと端末の控えを戻さないように）。時刻を省くと、順番が来たときの端末の時刻を送る。
 */
export function saveSubscription(
  pid: string,
  subscription: PushSubscription,
  notifyTime?: string,
): Promise<void> {
  const save = lastSave.then(async () => {
    const saved = await putPushSubscription(
      pid,
      toSubscriptionRequest(subscription, notifyTime ?? loadNotifyTime()),
    );
    saveNotifyTime(saved.notify_time);
  });
  lastSave = save.catch(() => undefined);
  return save;
}

/**
 * 許可を取った後の登録。サーバーが断ったら端末の登録も戻す（ブラウザだけオンで、
 * サーバーに無い状態を作らない）。
 */
export async function turnOn(
  pid: string,
  publicKey: string,
  notifyTime: string,
): Promise<PushSubscription> {
  const subscription = await subscribeDevice(publicKey);
  try {
    await saveSubscription(pid, subscription, notifyTime);
    return subscription;
  } catch (err) {
    await subscription.unsubscribe().catch(() => false);
    throw err;
  }
}

/**
 * 端末の登録を解除してからサーバーの行を消す。解除できれば、もう通知は届かない。
 * DELETE が失敗して行が残っても、次に送ったときに 404・410 で消えるので失敗にしない。
 */
export async function turnOff(
  pid: string,
  subscription: PushSubscription,
): Promise<void> {
  const { endpoint } = subscription;
  const removed = await subscription.unsubscribe();
  // false は「解除できなかった」か「もう解除されていた」。端末に残っているときだけ失敗にする
  if (!removed && (await isStillSubscribed(endpoint))) {
    throw new Error("unsubscribe failed");
  }
  await deletePushSubscription(pid, endpoint).catch(() => undefined);
}

/** 試しに送る。サーバーに行が無ければ（404。DB の作り直しなど）登録し直して1回だけやり直す。 */
export async function sendTest(
  pid: string,
  subscription: PushSubscription,
  notifyTime: string,
): Promise<void> {
  try {
    await sendPushTest(pid, subscription.endpoint);
  } catch (err) {
    if (!isApiError(err) || err.status !== 404) {
      throw err;
    }
    await saveSubscription(pid, subscription, notifyTime);
    await sendPushTest(pid, subscription.endpoint);
  }
}

export function testErrorKeyOf(err: unknown): string {
  return isApiError(err) && err.status === 429
    ? TEST_TOO_SOON_KEY
    : GENERIC_ERROR_KEY;
}

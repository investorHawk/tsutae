/**
 * オンの端末の登録をサーバーへ送り直す（docs/plan-device-records.md §4.3）。
 * サーバーの行だけが無い・別の患者のままのときに、設定を開かなくても毎日の通知が正しく届くように、
 * アプリを開いたとき・戻ってきたとき・番号を登録したときに行う。許可は求めず、登録も増やさない。
 * 失敗は出さない（記録の邪魔をしない。次に開いたときにやり直す）。
 */
import { useEffect } from "react";
import { loadPid } from "../../patient/pid";
import { isPushSupported } from "../../patient/pushDevice";
import {
  dropGoneSubscription,
  isSubscriptionGone,
  saveSubscription,
  savesSettled,
} from "./pushActions";
import { loadPushState, statusOfState, type PushState } from "./pushState";

let latest: Promise<void> = Promise.resolve();

type DroppedListener = (endpoint: string) => void;

const droppedListeners = new Set<DroppedListener>();

/** 聞き手のいない間に解除した登録（アプリを開いて読み込みの間など）。次の聞き手に1回だけ伝える。 */
let unheardDrop: string | null = null;

/**
 * 送り直しで「送信先に消された」と分かり、端末でも解除したときに呼ぶ（設定の画面が
 * オフの表示と理由を出せるように）。解除の関数を返す。
 */
export function onSubscriptionDropped(listener: DroppedListener): () => void {
  droppedListeners.add(listener);
  if (unheardDrop !== null) {
    const endpoint = unheardDrop;
    unheardDrop = null;
    listener(endpoint);
  }
  return () => {
    droppedListeners.delete(listener);
  };
}

function tellDropped(endpoint: string): void {
  if (droppedListeners.size === 0) {
    unheardDrop = endpoint;
    return;
  }
  droppedListeners.forEach((listener) => listener(endpoint));
}

async function resendOnce(): Promise<void> {
  const pid = loadPid();
  if (!pid || !isPushSupported()) {
    return;
  }
  let state: PushState;
  try {
    state = await loadPushState();
  } catch {
    return;
  }
  const { subscription } = state;
  if (statusOfState(state) !== "on" || !subscription) {
    return;
  }
  try {
    await saveSubscription(pid, subscription);
  } catch (err) {
    if (isSubscriptionGone(err)) {
      await dropGoneSubscription(subscription);
      tellDropped(subscription.endpoint);
    }
  }
}

/** 送り直す。呼ばれた順に1つずつ行う（前の番号の分が後から届かないように）。失敗しない。 */
export function resendSubscription(): Promise<void> {
  latest = latest.then(resendOnce);
  return latest;
}

/**
 * 送り直しと時刻の保存が終わってから状態を読む（送信先に消された登録をオンと見せない。
 * 保存の途中でタブを移って戻っても、新しい時刻を出す）。
 */
export function settledPushState(): Promise<PushState> {
  return latest.then(savesSettled).then(loadPushState);
}

/** アプリを開いたとき・戻ってきたときに送り直す（戻る間に DB が新しくなることがある）。 */
export function useResendSubscription(): void {
  useEffect(() => {
    void resendSubscription();
    const onChange = () => {
      if (document.visibilityState === "visible") {
        void resendSubscription();
      }
    };
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
}

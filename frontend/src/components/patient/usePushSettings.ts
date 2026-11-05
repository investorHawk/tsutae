import { useEffect, useState } from "react";
import { loadNotifyTime, saveNotifyTime } from "../../patient/notifyTime";
import { askPermission, currentPermission } from "../../patient/pushDevice";
import {
  saveSubscription,
  sendTest as sendTestTo,
  testErrorKeyOf,
  turnOff,
  turnOn,
} from "./pushActions";
import { GENERIC_ERROR_KEY, isNotRegistered } from "./patientApi";
import { statusOfState, type PushState } from "./pushState";
import type { PushStatus } from "./pushStatus";

const ENABLE_FAILED_KEY = "notify.enable_failed";
const NOT_ALLOWED_KEY = "notify.not_allowed";
const TIME_SAVED_KEY = "notify.time_saved";
const TEST_SENT_KEY = "notify.test_sent";

export type PushFeedback = { kind: "done" | "error"; key: string };

export interface PushSettings {
  status: PushStatus;
  notifyTime: string;
  busy: boolean;
  feedback: PushFeedback | null;
  notRegistered: boolean;
  enable: () => void;
  disable: () => void;
  changeTime: (time: string) => void;
  sendTest: () => void;
}

/** 操作の間の「送っています」と、結果の知らせ。401・403 は番号の入力欄へ回す。 */
function usePushTask() {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<PushFeedback | null>(null);
  const [notRegistered, setNotRegistered] = useState(false);

  async function run(
    task: () => Promise<void>,
    failKeyOf: (err: unknown) => string,
  ) {
    setBusy(true);
    setFeedback(null);
    try {
      await task();
    } catch (err) {
      if (isNotRegistered(err)) {
        setNotRegistered(true);
      } else {
        setFeedback({ kind: "error", key: failKeyOf(err) });
      }
    } finally {
      setBusy(false);
    }
  }

  return { busy, feedback, notRegistered, setFeedback, setNotRegistered, run };
}

/** 端末の設定で許可を直して戻ってきたときに、案内を出し続けないよう読み直す。 */
function usePermission(initial: NotificationPermission) {
  const [permission, setPermission] = useState(initial);
  useEffect(() => {
    const reread = () => setPermission(currentPermission());
    document.addEventListener("visibilitychange", reread);
    return () => document.removeEventListener("visibilitychange", reread);
  }, []);
  return [permission, setPermission] as const;
}

/**
 * 設定の画面の毎日のお知らせ（docs/plan-device-records.md §4.5）。
 * 開いたときにオンなら登録を送り直す（DB を作り直すと、画面はオンなのに届かなくなるため）。
 */
export function usePushSettings(pid: string, initial: PushState): PushSettings {
  const { publicKey } = initial;
  const [permission, setPermission] = usePermission(initial.permission);
  const [subscription, setSubscription] = useState(initial.subscription);
  const [notifyTime, setNotifyTime] = useState(loadNotifyTime);
  const task = usePushTask();
  const status = statusOfState({ publicKey, permission, subscription });

  useEffect(() => {
    if (status === "on" && subscription) {
      saveSubscription(pid, subscription, notifyTime).catch((err: unknown) => {
        // 他の失敗は次に開いたときにやり直す。画面は今の状態のまま使える
        if (isNotRegistered(err)) {
          task.setNotRegistered(true);
        }
      });
    }
    // 開いたときの1回だけ
  }, []);

  function enable() {
    // iPhone は押した直後でないと許可を求められないので、await より前に呼ぶ
    const asked = askPermission();
    void task.run(
      async () => {
        const answer = await asked;
        setPermission(answer);
        if (answer === "default") {
          task.setFeedback({ kind: "error", key: NOT_ALLOWED_KEY });
        }
        if (answer === "granted" && publicKey !== null) {
          setSubscription(await turnOn(pid, publicKey, notifyTime));
        }
      },
      () => ENABLE_FAILED_KEY,
    );
  }

  function disable() {
    if (!subscription) {
      return;
    }
    void task.run(
      async () => {
        await turnOff(pid, subscription);
        setSubscription(null);
      },
      () => GENERIC_ERROR_KEY,
    );
  }

  function changeTime(time: string) {
    const previous = notifyTime;
    setNotifyTime(time);
    if (status !== "on" || !subscription) {
      saveNotifyTime(time);
      return;
    }
    void task.run(
      async () => {
        await saveSubscription(pid, subscription, time);
        task.setFeedback({ kind: "done", key: TIME_SAVED_KEY });
      },
      () => {
        setNotifyTime(previous);
        return GENERIC_ERROR_KEY;
      },
    );
  }

  function sendTest() {
    if (!subscription) {
      return;
    }
    void task.run(async () => {
      await sendTestTo(pid, subscription, notifyTime);
      task.setFeedback({ kind: "done", key: TEST_SENT_KEY });
    }, testErrorKeyOf);
  }

  return {
    status,
    notifyTime,
    busy: task.busy,
    feedback: task.feedback,
    notRegistered: task.notRegistered,
    enable,
    disable,
    changeTime,
    sendTest,
  };
}

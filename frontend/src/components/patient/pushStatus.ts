/**
 * 毎日のお知らせの状態の判定と、選べる時刻（docs/plan-device-records.md §4.5）。
 * 端末の API には触らない純関数だけを置く。
 */

export type PushStatus = "unsupported" | "no_key" | "denied" | "on" | "off";

export interface PushFacts {
  /** 端末が通知を使えるか（iPhone はホーム画面の外だと使えない） */
  supported: boolean;
  /** サーバーに通知の鍵があるか（GET push-config） */
  hasKey: boolean;
  permission: NotificationPermission;
  /** この端末に今の鍵の通知の登録があるか */
  subscribed: boolean;
}

/**
 * 直せない理由から順に見る。許可が消えた後は登録が残っていても届かないのでオンとは言わない。
 */
export function pushStatusOf(facts: PushFacts): PushStatus {
  if (!facts.supported) {
    return "unsupported";
  }
  if (!facts.hasKey) {
    return "no_key";
  }
  if (facts.permission === "denied") {
    return "denied";
  }
  return facts.subscribed && facts.permission === "granted" ? "on" : "off";
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** 選べる時刻（JST の HH:MM。30 分刻み）。 */
export const NOTIFY_TIMES: readonly string[] = Object.freeze(
  Array.from({ length: 48 }, (_, i) => {
    const minutes = i % 2 === 0 ? "00" : "30";
    return `${pad(Math.floor(i / 2))}:${minutes}`;
  }),
);

export const DEFAULT_NOTIFY_TIME = "20:00";

export function isNotifyTime(value: string | null): value is string {
  return value !== null && NOTIFY_TIMES.includes(value);
}

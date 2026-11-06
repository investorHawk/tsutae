/**
 * この端末で選んだ通知の時刻の写し。時刻の正本はサーバーだが、読む API が無いので
 * （PUT の応答で返るだけ）、設定の画面に出す値を端末にも置く（docs/decisions.md）。
 */
import {
  DEFAULT_NOTIFY_TIME,
  isNotifyTime,
} from "../components/patient/pushStatus";

const STORAGE_KEY = "tsutae.notify_time";

export function loadNotifyTime(): string {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isNotifyTime(value) ? value : DEFAULT_NOTIFY_TIME;
  } catch {
    return DEFAULT_NOTIFY_TIME;
  }
}

export function saveNotifyTime(time: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, time);
  } catch {
    // 保存領域が使えない環境では、次に開くと既定の時刻が出るだけ
  }
}

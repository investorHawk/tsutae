/** 医師画面の日時表示。全て Asia/Tokyo で出す（サーバーの時刻は +09:00 付き）。 */

const TIME_ZONE = "Asia/Tokyo";

const DATE_TIME = new Intl.DateTimeFormat("ja-JP", {
  timeZone: TIME_ZONE,
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const TIME = new Intl.DateTimeFormat("ja-JP", {
  timeZone: TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function parse(iso: string): Date | null {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : new Date(ms);
}

/** "11/09 10:23"。読めない値はそのまま返す。 */
export function formatDateTime(iso: string): string {
  const date = parse(iso);
  return date ? DATE_TIME.format(date) : iso;
}

/** "10:23:05"。読めない値はそのまま返す。 */
export function formatTime(iso: string): string {
  const date = parse(iso);
  return date ? TIME.format(date) : iso;
}

/** 経過時間 "+1.2秒" / "+1分05秒"。負・数でない値は空文字。 */
export function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) {
    return "";
  }
  if (ms < 60_000) {
    return `+${(ms / 1000).toFixed(1)}秒`;
  }
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `+${minutes}分${seconds}秒`;
}

/** 所要時間 "1.2秒"（duration_ms の表示）。 */
export function formatDuration(ms: number): string {
  return formatElapsed(ms).replace(/^\+/, "");
}

/**
 * 医師画面の日付の書き方（1つにそろえる）: 「11月9日（月）」、時刻つきは「11月9日（月）18:16」。
 * 年が今年（東京の今日の年）と違う時だけ「2025年11月9日（日）」。全て Asia/Tokyo で出す。
 * 今年の判定だけは端末の時計を使う（コースや Day の計算ではないので、サーバーの今日は要らない。
 * デモの TSUTAE_TODAY とは年が同じ）。日付の入力欄（type=date）はこの書き方にしない。
 */

const TIME_ZONE = "Asia/Tokyo";
const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"] as const;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

interface Ymd {
  year: number;
  month: number;
  day: number;
}

const PARTS = new Intl.DateTimeFormat("en-US", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

interface TokyoParts extends Ymd {
  hour: string;
  minute: string;
}

function tokyoParts(date: Date): TokyoParts {
  const parts = Object.fromEntries(
    PARTS.formatToParts(date).map((p) => [p.type, p.value]),
  );
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: String(parts.hour).padStart(2, "0"),
    minute: String(parts.minute).padStart(2, "0"),
  };
}

/** "YYYY-MM-DD" を暦どおりに読む（Date.parse の UTC の0時に頼らない）。 */
function parseIsoDate(value: string): Ymd | null {
  const m = ISO_DATE.exec(value);
  if (!m) {
    return null;
  }
  const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const d = new Date(Date.UTC(year, month - 1, day));
  const valid =
    d.getUTCFullYear() === year &&
    d.getUTCMonth() === month - 1 &&
    d.getUTCDate() === day;
  return valid ? { year, month, day } : null;
}

function parseDateTime(value: string): Date | null {
  if (!value.includes("T")) {
    return null;
  }
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : new Date(ms);
}

function dayText(ymd: Ymd, thisYear: number): string {
  const weekday =
    WEEKDAYS[new Date(Date.UTC(ymd.year, ymd.month - 1, ymd.day)).getUTCDay()];
  const year = ymd.year === thisYear ? "" : `${ymd.year}年`;
  return `${year}${ymd.month}月${ymd.day}日（${weekday}）`;
}

/**
 * 今年を決める時計。既定は端末の今。テストは src/test/setup.ts で 2026-11-09 に止める
 * （実行する年によって「2026年」が付いたり付かなかったりしないように）。
 */
export const dayLabelClock = { now: (): Date => new Date() };

/**
 * 日付（"YYYY-MM-DD"）は「11月9日（月）」、日時（ISO 8601）は「11月9日（月）18:16」。
 * now は今年を決める時刻（既定は dayLabelClock）。読めない値はそのまま返す。
 */
export function formatDay(
  value: string,
  now: Date = dayLabelClock.now(),
): string {
  const thisYear = tokyoParts(now).year;
  const date = parseIsoDate(value);
  if (date) {
    return dayText(date, thisYear);
  }
  const at = parseDateTime(value);
  if (!at) {
    return value;
  }
  const parts = tokyoParts(at);
  return `${dayText(parts, thisYear)}${parts.hour}:${parts.minute}`;
}

/** 日時の東京の「18:16」。読めない値は空文字。 */
export function formatClock(value: string): string {
  const at = parseDateTime(value);
  if (!at) {
    return "";
  }
  const parts = tokyoParts(at);
  return `${parts.hour}:${parts.minute}`;
}

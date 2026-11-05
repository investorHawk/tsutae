/**
 * スマホに保存する仮名ID（spec 3.1 P0）。患者 API の経路 {pid} に使う。
 * 登録（P0）で保存し、今日の記録（P1）・自分の記録（P2）で読む。
 */

const STORAGE_KEY = "tsutae.pid";

/** docs/architecture.md §2: "P-" + 英大文字数字8桁 */
export const PID_PATTERN = /^P-[A-Z0-9]{8}$/;

export function isValidPid(value: string): boolean {
  return PID_PATTERN.test(value);
}

/** 長音・ダッシュの類（NFKC の後に残るもの）。 */
const DASH_LIKE =
  /[\u2010-\u2015\u2212\u2500\u2501\u30FC\uFE58\uFE63\uFF0D\uFF70]/g;
const PID_BODY = /^[A-Z0-9]{8}$/;

/**
 * 手で入れた番号を仮名ID の形に揃える（前後の空白・全角・小文字・長音やダッシュ・
 * 「P-」の抜け）。形が正しいとは限らないので、呼ぶ側で isValidPid に通す。
 */
export function normalizePidInput(raw: string): string {
  const text = raw
    .normalize("NFKC")
    .trim()
    .toUpperCase()
    .replace(DASH_LIKE, "-");
  return PID_BODY.test(text) ? `P-${text}` : text;
}

export function loadPid(): string | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value !== null && isValidPid(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * 形式が正しくなければ例外。保存領域に書けなくても例外（localStorage の例外のまま）。
 * 登録（P0）は API を呼ぶ前にこれで保存し、登録が失敗したら restorePid で元に戻す
 * （Cookie だけ発行されて仮名ID が残らない食い違いを作らない）。
 */
export function savePid(pid: string): void {
  if (!isValidPid(pid)) {
    throw new Error("pid format is not valid");
  }
  window.localStorage.setItem(STORAGE_KEY, pid);
}

export function clearPid(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 保存領域が使えない環境では何もしない
  }
}

/** 登録の前に読んでおいた値に戻す（null なら消す）。戻せなくても例外にしない。 */
export function restorePid(previous: string | null): void {
  if (previous === null) {
    clearPid();
    return;
  }
  try {
    savePid(previous);
  } catch {
    clearPid();
  }
}

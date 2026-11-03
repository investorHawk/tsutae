/**
 * API の失敗の扱い（医師画面）。サーバーは {"error": "<code>"} を返す。
 * 画面には日本語の説明と code をそのまま並べる（code は API が増やしてもよい）。
 */
import { isApiError, UNKNOWN_ERROR } from "../../api/http";

const MESSAGES: Readonly<Record<string, string>> = {
  network_error: "サーバーにつながりません",
  unknown_error: "処理できませんでした",
  invalid_response: "サーバーの応答を読めませんでした",
  not_found: "見つかりません",
  not_logged_in: "ログインしてください",
  unauthorized: "ログインしてください",
  unknown_patient: "その仮名IDの患者は登録されていません",
  course_duplicate: "同じコース番号がすでにあります",
  course_order: "実投与日がコース番号の順に増えていません",
  course_patient_mismatch: "別の患者のコースが混ざっています",
  course_not_found: "そのコースは登録されていません",
  schedule_mismatch: "日程とコースが合いません",
  invalid_course_no: "コース番号は1以上の整数で入れてください",
  missing_infusion_date: "実投与日を入れてください",
  invalid_date: "日付は YYYY-MM-DD の形で、暦にある日を入れてください",
  note_too_long: "メモは200字までです",
  invalid_visit_id: "受診の番号が正しくありません",
};

export function errorCode(err: unknown): string {
  return isApiError(err) ? err.code : UNKNOWN_ERROR;
}

export function isUnauthorized(err: unknown): boolean {
  return isApiError(err) && err.isUnauthorized;
}

export function describeError(code: string): string {
  return MESSAGES[code] ?? MESSAGES[UNKNOWN_ERROR];
}

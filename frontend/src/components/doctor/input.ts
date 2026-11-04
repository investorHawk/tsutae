/** 外から来た値（経路のパラメータ・API の本文）の検査。 */
import { isRecord } from "../../api/validate";

export { invalidResponse, isRecord, listOf } from "../../api/validate";

/** 経路の visitId。正の整数の文字列だけを数にする。 */
export function parseVisitId(value: string | undefined): number | null {
  return value !== undefined && /^[1-9]\d{0,9}$/.test(value)
    ? Number(value)
    : null;
}

/** state.from が医師画面の経路（ログイン画面以外）ならそれを、違えば fallback。 */
export function safeDoctorPath(state: unknown, fallback = "/doctor"): string {
  const from = isRecord(state) ? state.from : undefined;
  if (typeof from !== "string") {
    return fallback;
  }
  const isDoctorPath = from === "/doctor" || from.startsWith("/doctor/");
  const isLogin = from === "/doctor/login" || from.startsWith("/doctor/login/");
  return isDoctorPath && !isLogin && !from.startsWith("//") ? from : fallback;
}

/** 患者画面での API の失敗の扱い。文面ではなく patient_strings のキーを返す。 */
import { isApiError } from "../../api/http";

export const NOT_REGISTERED_KEY = "error.not_registered";
export const GENERIC_ERROR_KEY = "error.generic";
const TOO_MANY_KEY = "error.too_many_attempts";

/** Cookie が無い・経路の pid と違う（401/403）。 */
export function isNotRegistered(err: unknown): boolean {
  return isApiError(err) && (err.status === 401 || err.status === 403);
}

export function errorKeyOf(err: unknown): string {
  return isNotRegistered(err) ? NOT_REGISTERED_KEY : GENERIC_ERROR_KEY;
}

/**
 * POST register の失敗。仮名ID の誤り（400・404・422）の文は画面ごとに違うので受け取る
 * （QR の画面と番号の入力）。404 は API が失敗の回数に数え、続くと 429 になる。
 */
export function registerErrorKeyOf(err: unknown, invalidKey: string): string {
  if (isApiError(err) && err.status === 429) {
    return TOO_MANY_KEY;
  }
  if (isApiError(err) && [400, 404, 422].includes(err.status)) {
    return invalidKey;
  }
  return GENERIC_ERROR_KEY;
}

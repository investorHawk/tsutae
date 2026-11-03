/** 患者画面での API の失敗の扱い。文面ではなく patient_strings のキーを返す。 */
import { isApiError } from "../../api/http";

export const NOT_REGISTERED_KEY = "error.not_registered";
export const GENERIC_ERROR_KEY = "error.generic";

/** Cookie が無い・経路の pid と違う（401/403）。 */
export function isNotRegistered(err: unknown): boolean {
  return isApiError(err) && (err.status === 401 || err.status === 403);
}

export function errorKeyOf(err: unknown): string {
  return isNotRegistered(err) ? NOT_REGISTERED_KEY : GENERIC_ERROR_KEY;
}

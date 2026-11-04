/**
 * ビルドに同梱する定型文。正本は backend/tsutae/patient_strings.json（API の
 * GET /api/patient/strings が返すのと同じファイル）。用途は2つ:
 * - 読み込み時の検証: ここにあるキーは全て、サーバーの本文にも文字列で無ければならない
 * - 読み込みに失敗した時の代わり（承認済みの同じ文面なので、患者画面の約束を破らない）
 */
import raw from "../../../backend/tsutae/patient_strings.json?raw";
import type { PatientStrings } from "../api/types";

function parseBundled(text: string): PatientStrings {
  const data: unknown = JSON.parse(text);
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("patient_strings.json is not an object");
  }
  const entries = Object.entries(data).filter(
    (pair): pair is [string, string] => typeof pair[1] === "string",
  );
  return Object.freeze(Object.fromEntries(entries));
}

export const BUNDLED_STRINGS: PatientStrings = parseBundled(raw);

/** サーバーの本文に必ず要るキー（同梱の正本のキー全て）。 */
export const REQUIRED_KEYS: readonly string[] = Object.freeze(
  Object.keys(BUNDLED_STRINGS),
);

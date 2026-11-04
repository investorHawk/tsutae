/**
 * D4 の画面テスト用（本番コードからは import しない）。設定画面は選んだ Skill の
 * 今の中身（GET skills/{name}）を読むので、その偽の応答を名前ごとに作る。
 */
import type { SkillContentResponse } from "../../api/types";
import type { RouteValue } from "./testing";

/** 中身の本文（質問なし・合成）。 */
export function skillContent(name: string, version = 1): SkillContentResponse {
  return {
    name,
    version,
    description: "（合成）テスト用の Skill",
    questions: [],
    text: `---\nname: ${name}\nversion: ${version}\n---\n`,
  };
}

/** names の Skill の「GET /api/doctor/skills/{name}」の応答。 */
export function skillContentRoutes(
  names: readonly string[],
): Record<string, RouteValue> {
  return Object.fromEntries(
    names.map((name) => [`GET /api/doctor/skills/${name}`, skillContent(name)]),
  );
}

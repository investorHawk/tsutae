/**
 * 緊急時の固定規則（docs/plan-device-records.md §5.3）。判定はコードの閾値比較だけで、
 * モデルは関わらない。体温はサーバーに送らないので、案内を出すのは画面のコード。
 * backend/tsutae/api/fixed_rules.py と同じ判定で、同じ表
 * （src/test/fixtures/fixed_rule_cases.json）でテストする。
 *
 * - 対象はクローズ回答の体温（value=measured）だけ。自由記載は読まない
 * - 体温 >= threshold_celsius なら、その規則の patient_string_key を返す
 * - 規則の順に並べ、同じキーは1回だけ。引数は書き換えない
 */
import type { ClosedAnswer, EntryCreate, FixedRule } from "../api/types";

type RuleEntry = Pick<EntryCreate, "too_sick"> & {
  answers?: readonly ClosedAnswer[];
};

function fires(entry: RuleEntry, rule: FixedRule): boolean {
  const answer = entry.answers?.find(
    (a) => a.question_key === rule.question_key,
  );
  return (
    answer?.value === "measured" &&
    typeof answer.temperature === "number" &&
    answer.temperature >= rule.threshold_celsius
  );
}

/** 記録が当てはまる固定規則の patient_strings のキー（例 `fixed_rule.fever_38`）。 */
export function noticesFor(
  entry: RuleEntry,
  rules: readonly FixedRule[],
): string[] {
  if (entry.too_sick === true) {
    return [];
  }
  const keys = rules
    .filter((rule) => fires(entry, rule))
    .map((rule) => rule.patient_string_key);
  return [...new Set(keys)];
}

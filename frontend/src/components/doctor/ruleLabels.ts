/**
 * 二次検出（H1 の規則）の説明。tsutae.masking.detect_identifiers の規則名と、
 * pipeline の known_identifier。画面には説明だけを出し、規則名は title に残す（D7-1）。
 */
const RULE_LABELS: Readonly<Record<string, string>> = {
  unknown_before_honorific: "敬称の前に、辞書にない語がある（人名の疑い）",
  long_digits: "7桁以上の数字列がある（電話番号・番号の疑い）",
  at_mark: "@ がある（メールアドレスの疑い）",
  before_facility: "施設名らしき語がある（病院名の疑い）",
  address_number: "番地らしき数字の並びがある（住所の疑い）",
  id_like: "英字とハイフンと番号の並びがある（ID・受付番号の疑い）",
  known_identifier: "この患者の仮名ID か受付番号が書かれている",
};

export const UNKNOWN_RULE_LABEL = "伏せ字漏れの疑い";

/** 規則名の日本語の説明。知らない規則は一般の説明。 */
export function ruleLabel(reason: string): string {
  return RULE_LABELS[reason] ?? UNKNOWN_RULE_LABEL;
}

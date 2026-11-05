/**
 * 患者の画面（D2）の記録の、質問の短い名前と回答の日本語（決まった文言だけ）。
 * 短い症状名は患者画面の `symptom.<question_key>`（backend/tsutae/patient_strings.json）と
 * 同じ語にする（テストで照合）。紙の経過表（backend/tsutae/report/labels.py）は
 * hand_foot を「手足の皮膚」と書くので、そこだけ紙と画面で語が違う。
 * 並びは経過表の列の順。知らない質問（D4 で足した質問など）は記録の版の form の短い名前
 * （API の question_label。v1.1）、それも無ければ key をそのまま出す。
 */
import type { AnswerValue } from "../../api/types";

const QUESTION_LABELS: Readonly<Record<string, string>> = {
  numbness: "しびれ",
  diarrhea: "下痢",
  stomatitis: "口内炎",
  nausea_appetite: "吐き気・食欲",
  hand_foot: "手のひら・足の裏",
  fever: "体温",
};

/** 既知の質問の列の順。 */
export const QUESTION_ORDER: readonly string[] = Object.keys(QUESTION_LABELS);

const VALUE_LABELS: Readonly<Record<AnswerValue, string>> = {
  none: "なし",
  present: "ある",
  hard: "つらい",
  not_measured: "測っていない",
  measured: "測った",
};

export function questionLabel(key: string, label?: string | null): string {
  return QUESTION_LABELS[key] ?? (label || key);
}

export function valueLabel(value: AnswerValue): string {
  return VALUE_LABELS[value] ?? value;
}

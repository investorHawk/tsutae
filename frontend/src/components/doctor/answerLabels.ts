/**
 * 患者の画面（D2）の記録の、クローズ回答の短い表記（決まった文言だけ）。
 * 質問の短い名前と回答の日本語は backend/tsutae/report/labels.py（紙の経過表）と同じ。
 * 知らない質問（D4 で足した質問など）は key をそのまま出す。
 */
import type { DoctorEntryAnswer } from "../../api/types";

const QUESTION_LABELS: Readonly<Record<string, string>> = {
  numbness: "しびれ",
  diarrhea: "下痢",
  stomatitis: "口内炎",
  nausea_appetite: "吐き気・食欲",
  hand_foot: "手足の皮膚",
  fever: "体温",
};

const VALUE_LABELS: Readonly<Record<string, string>> = {
  none: "なし",
  present: "ある",
  hard: "つらい",
  not_measured: "測っていない",
  measured: "測った",
};

export function questionLabel(key: string): string {
  return QUESTION_LABELS[key] ?? key;
}

/** 「下痢 つらい」「体温 38.2℃」「体温 測っていない」。 */
export function answerText(answer: DoctorEntryAnswer): string {
  const value =
    answer.value === "measured" && answer.temperature !== null
      ? `${answer.temperature.toFixed(1)}℃`
      : (VALUE_LABELS[answer.value] ?? answer.value);
  return `${questionLabel(answer.question_key)} ${value}`;
}

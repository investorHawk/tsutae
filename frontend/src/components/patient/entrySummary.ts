/**
 * 記録1件の短い要約（P3-1・P2-4）。これまでの記録の一行に並べるタグ
 * （「しびれ」「下痢」「37.8℃」「書いたこと」「代理」）の元になる項目を、記録の順に
 * 並べる。文面は持たない（描くときに t() で引く）。
 * - つらくて書けない: それだけ
 * - ある・つらい・測った体温だけを出す（なし・測っていないは出さない）。答えはあるのに
 *   全て出さないものなら all_none（「どれも なし」）
 * - 自由記載があれば free_text（中身は出さない。詳しくは開いて見る）
 * - 家族が代わりに入力した記録なら最後に proxy
 */
import type { AnswerValue, DeviceEntry } from "../../api/types";

export interface SummaryAnswer {
  questionKey: string;
  value: AnswerValue;
  temperature?: number | null;
  /** 短い症状名（symptom.*）が無いときに出す質問文。無ければ null */
  questionText: string | null;
}

export interface SummarySource {
  tooSick: boolean;
  answers: readonly SummaryAnswer[];
  freeText: string | null;
  /** 家族が代わりに入力した記録（無ければ false とみなす） */
  byProxy?: boolean;
}

export type SummaryItem =
  | { kind: "too_sick" }
  | {
      kind: "answer";
      questionKey: string;
      value: "present" | "hard";
      questionText: string | null;
    }
  | {
      kind: "temperature";
      questionKey: string;
      temperature: number;
      questionText: string | null;
    }
  | { kind: "all_none" }
  | { kind: "free_text" }
  | { kind: "proxy" };

function answerItem(answer: SummaryAnswer): SummaryItem | null {
  const { questionKey, value, questionText } = answer;
  if (value === "present" || value === "hard") {
    return { kind: "answer", questionKey, value, questionText };
  }
  if (value === "measured" && typeof answer.temperature === "number") {
    return {
      kind: "temperature",
      questionKey,
      temperature: answer.temperature,
      questionText,
    };
  }
  return null;
}

function bodyItems(source: SummarySource): SummaryItem[] {
  if (source.tooSick) {
    return [{ kind: "too_sick" }];
  }
  const answers = source.answers.flatMap((a) => {
    const item = answerItem(a);
    return item === null ? [] : [item];
  });
  const items: SummaryItem[] =
    source.answers.length > 0 && answers.length === 0
      ? [{ kind: "all_none" }]
      : answers;
  const hasFreeText = (source.freeText ?? "").trim().length > 0;
  return hasFreeText ? [...items, { kind: "free_text" }] : items;
}

export function summarizeEntry(source: SummarySource): SummaryItem[] {
  const items = bodyItems(source);
  return source.byProxy === true ? [...items, { kind: "proxy" }] : items;
}

/** 要約の元を作る。質問の文は記録に持たせた写し（記録時点の質問集の文）。 */
export function summarySourceOf(entry: DeviceEntry): SummarySource {
  return {
    tooSick: entry.kind === "too_sick",
    answers: entry.answers.map((a) => ({
      questionKey: a.question_key,
      value: a.value,
      temperature: a.temperature,
      questionText: a.question_text,
    })),
    freeText: entry.free_text,
    byProxy: entry.by_proxy,
  };
}

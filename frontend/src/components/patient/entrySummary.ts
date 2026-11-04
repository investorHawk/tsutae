/**
 * 記録1件の短い要約（P3-1・P2-4）。「しびれ つらい／下痢 ある／体温 37.8℃／書いたこと あり」
 * の元になる項目を、記録の順に並べる。文面は持たない（描くときに t() で引く）。
 * - つらくて書けない: それだけ
 * - ある・つらい・測った体温だけを出す（なし・測っていないは出さない）。答えはあるのに
 *   全て出さないものなら all_none（「どれも なし」）
 * - 自由記載があれば最後に free_text（中身は出さない。詳しくは開いて見る）
 */
import type {
  AnswerValue,
  EntryCreate,
  PatientEntry,
  Question,
} from "../../api/types";

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
  | { kind: "free_text" };

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

export function summarizeEntry(source: SummarySource): SummaryItem[] {
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

function isEntry(value: PatientEntry | EntryCreate): value is PatientEntry {
  return "kind" in value;
}

/**
 * 要約の元を作る。GET entries の記録なら question_text を、送った EntryCreate なら
 * 質問集の文を使う。
 */
export function summarySourceOf(
  entry: PatientEntry | EntryCreate,
  questions: readonly Question[] = [],
): SummarySource {
  if (isEntry(entry)) {
    return {
      tooSick: entry.kind === "too_sick",
      answers: entry.answers.map((a) => ({
        questionKey: a.question_key,
        value: a.value,
        temperature: a.temperature,
        questionText: a.question_text,
      })),
      freeText: entry.free_text,
    };
  }
  const texts = new Map(questions.map((q) => [q.key, q.text]));
  return {
    tooSick: entry.too_sick === true,
    answers: (entry.answers ?? []).map((a) => ({
      questionKey: a.question_key,
      value: a.value,
      temperature: a.temperature ?? null,
      questionText: texts.get(a.question_key) ?? null,
    })),
    freeText: entry.free_text ?? null,
  };
}

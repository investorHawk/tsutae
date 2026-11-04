/**
 * 患者画面のテスト用データ。定型文は手書きの写しではなく実物
 * （backend/tsutae/patient_strings.json）を読む。キーの食い違いをテストで拾うため。
 */
import rawStrings from "../../../../../backend/tsutae/patient_strings.json?raw";
import type {
  PatientEntry,
  PatientStrings,
  Question,
  QuestionsResponse,
} from "../../../api/types";

function parseStrings(raw: string): PatientStrings {
  const data: unknown = JSON.parse(raw);
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("patient_strings.json がオブジェクトでない");
  }
  return Object.freeze({ ...(data as Record<string, string>) });
}

/** patient_strings.json そのもの。 */
export const STRINGS: PatientStrings = parseStrings(rawStrings);

/** キーの定型文。無いキーはテストを落とす（書き間違いを拾う）。 */
export function s(key: string): string {
  const value = STRINGS[key];
  if (value === undefined) {
    throw new Error(`patient_strings.json に ${key} が無い`);
  }
  return value;
}

export const PID = "P-DEMO0001";

/** FOLFOX の質問集（合成。regimen-folfox@1 の写し）。 */
export const QUESTIONS: readonly Question[] = [
  {
    key: "numbness",
    text: "手足のしびれや冷たいものがさわりにくい感じはありましたか",
    answer_type: "three_level",
  },
  { key: "diarrhea", text: "下痢はありましたか", answer_type: "three_level" },
  {
    key: "stomatitis",
    text: "口の中の痛みや口内炎はありましたか",
    answer_type: "three_level",
  },
  {
    key: "nausea_appetite",
    text: "吐き気や食欲の落ち込みはありましたか",
    answer_type: "three_level",
  },
  { key: "fever", text: "熱を測りましたか", answer_type: "temperature" },
];

export const QUESTIONS_RESPONSE: QuestionsResponse = {
  skill_version: "regimen-folfox@1",
  questions: [...QUESTIONS],
  /** サーバーの今日（2026-11-09 は月曜） */
  today: "2026-11-09",
};

export function questionText(key: string): string {
  const q = QUESTIONS.find((item) => item.key === key);
  if (!q) {
    throw new Error(`質問 ${key} が無い`);
  }
  return q.text;
}

/**
 * 自分の記録（合成）。API の順（recorded_at 昇順）で並べてある。
 * question_text は記録の skill_version の質問集の文（§8）。
 */
export const ENTRIES: readonly PatientEntry[] = [
  {
    id: 11,
    recorded_at: "2026-10-29T21:05:00+09:00",
    record_date: "2026-10-29",
    kind: "too_sick",
    by_proxy: false,
    skill_version: "regimen-folfox@1",
    answers: [],
    free_text: null,
  },
  {
    id: 12,
    recorded_at: "2026-10-31T19:30:00+09:00",
    record_date: "2026-10-31",
    kind: "mixed",
    by_proxy: true,
    skill_version: "regimen-folfox@1",
    answers: [
      {
        question_key: "diarrhea",
        value: "present",
        temperature: null,
        question_text: questionText("diarrhea"),
      },
      {
        question_key: "fever",
        value: "measured",
        temperature: 37.9,
        question_text: questionText("fever"),
      },
    ],
    free_text: "点滴の次の日からおなかがゆるい",
  },
  {
    id: 13,
    recorded_at: "2026-11-02T08:10:00+09:00",
    record_date: "2026-11-02",
    kind: "free_text",
    by_proxy: false,
    skill_version: "regimen-folfox@1",
    answers: [],
    free_text: "しびれはだいぶ楽になった",
  },
];

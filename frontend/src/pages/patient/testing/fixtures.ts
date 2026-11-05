/**
 * 患者画面のテスト用データ。定型文は手書きの写しではなく実物
 * （backend/tsutae/patient_strings.json）を読む。キーの食い違いをテストで拾うため。
 */
import rawStrings from "../../../../../backend/tsutae/patient_strings.json?raw";
import type {
  DeviceEntry,
  PatientStrings,
  PatientVisitDay,
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
  fixed_rules: [
    {
      question_key: "fever",
      threshold_celsius: 38,
      patient_string_key: "fixed_rule.fever_38",
    },
  ],
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
 * 端末の記録（合成）。recorded_at 昇順で並べてある。
 * question_text は記録の skill_version の質問集の文の写し。ID は末尾の数で見分ける。
 */
export const ENTRIES: readonly DeviceEntry[] = [
  {
    pid: PID,
    client_entry_id: "00000000-0000-4000-8000-000000000011",
    recorded_at: "2026-10-29T21:05:00+09:00",
    record_date: "2026-10-29",
    kind: "too_sick",
    by_proxy: false,
    skill_version: "regimen-folfox@1",
    answers: [],
    free_text: null,
  },
  {
    pid: PID,
    client_entry_id: "00000000-0000-4000-8000-000000000012",
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
    pid: PID,
    client_entry_id: "00000000-0000-4000-8000-000000000013",
    recorded_at: "2026-11-02T08:10:00+09:00",
    record_date: "2026-11-02",
    kind: "free_text",
    by_proxy: false,
    skill_version: "regimen-folfox@1",
    answers: [],
    free_text: "しびれはだいぶ楽になった",
  },
];

/**
 * 自分の受診日（合成）。2026-10-30（金）9:20 の受付は、10-29 と 10-31 の記録の間に入る。
 * 既定の偽物の API（testing/api.ts）は受診を返さない（visits: []）。
 */
export const VISITS: readonly PatientVisitDay[] = [
  { visit_date: "2026-10-30", received_at: "2026-10-30T09:20:00+09:00" },
];

/** JS の trim は残すが受付は断る文字（貼り付けでしか入らない）。表は free_text_cases.json。 */
export const NEXT_LINE = "\u0085";
export const FILE_SEPARATOR = "\u001c";
export const LONE_SURROGATE = "\ud83d";
